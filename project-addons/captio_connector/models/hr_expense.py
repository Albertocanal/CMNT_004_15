from odoo import api, fields, models
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
import calendar
import requests
import json


class HrExpense(models.Model):

    _inherit = "hr.expense"

    @api.model
    def get_new_token_captio(self):

        client_id = self.env['ir.config_parameter'].sudo().get_param('captio.client_id')
        client_secret = self.env['ir.config_parameter'].sudo().get_param('captio.client_secret')
        url_token = self.env['ir.config_parameter'].sudo().get_param('captio.api_token')

        data = 'grant_type=client_credentials&scope=integrations_api&client_id=%s&client_secret=%s' % \
               (client_id, client_secret)
        response = requests.post(url_token, data=data)

        if response.status_code == 200:
            resp = json.loads(response.text)
            self.env.user.company_id.captio_token = resp['access_token']
            self.env.user.company_id.captio_token_expire = datetime.now() + \
                                                           relativedelta(seconds=resp['expires_in'])

    @api.model
    def assign_user_from_captio(self, captio_id):

        token = self.env.user.company_id.captio_token
        ckey = self.env['ir.config_parameter'].sudo().get_param('captio.customer_key')
        url_api = self.env['ir.config_parameter'].sudo().get_param('captio.api_endpoint')
        filters = '?filters={"Id":"%s"}' % captio_id

        response = requests.get('%s/v3.1/Users%s' % (url_api, filters),
                                headers={'Authorization': 'Bearer ' + token,
                                         'CustomerKey': ckey})
        if response.status_code == 200:
            resp = json.loads(response.text)
            user = self.env['res.users'].search([('login', '=', resp[0]["Email"])])
            if user:
                user.captio_id = captio_id
                return user

    @api.model
    def cron_import_captio_expenses(self):

        company = self.env.user.company_id
        country_code = self.env['ir.config_parameter'].sudo().get_param('country_code')
        url_api = self.env['ir.config_parameter'].sudo().get_param('captio.api_endpoint')

        if not company.captio_token_expire or \
                company.captio_token_expire < datetime.now().strftime('%Y-%m-%d %H:%M:%S'):
            # TODO: revisar si es mejor pasar el captio_token_expire a tipo datetime en vez del now a string
            self.get_new_token_captio()

        token = company.captio_token
        ckey = self.env['ir.config_parameter'].sudo().get_param('captio.customer_key')

        # Search for the reports with status 4 (Approved), and aproved after the last time we check
        filters = '?filters={"Status":"4","StatusDate":">%s"}' % (company.captio_last_date.replace(" ", "T") + "Z")
        response = requests.get('%s/v3.1/Reports%s' % (url_api, filters),
                                headers={'Authorization': 'Bearer ' + token,
                                         'CustomerKey': ckey})
        if response.status_code == 200:
            resp_repo = json.loads(response.text)

            for report in resp_repo:
                user = self.env['res.users'].search([('captio_id', '=', report["User"]["Id"])])
                if not user:
                    user = self.assign_user_from_captio(report["User"]["Id"])

                # Search for the expenses in the report
                # each expense will be an account.move so each movement can have its own date
                filters = '?filters={"Report_Id":"%s"}' % report["Id"]
                response = requests.get('%s/v3.1/Expenses%s' % (url_api, filters),
                                        headers={'Authorization': 'Bearer ' + token,
                                                 'CustomerKey': ckey})
                if response.status_code == 200:
                    resp_exp = json.loads(response.text)
                    if resp_exp:
                        for count, expense in enumerate(resp_exp):
                            exp_vals = []

                            # Create all the necessary data
                            if expense["PaymentMethod"]["Name"] in ('Tarjeta empresa', 'Carta di credito'):
                                payment_method = ' TJ '
                                journal = self.env['account.journal'].search([('expenses_journal', '=', True)])
                                close_account = user.card_account_id.id,
                            elif expense["PaymentMethod"]["Name"] in ('Efectivo', 'Contanti'):
                                payment_method = ' EF '
                                journal = self.env['account.journal'].search([('expenses_journal', '=', True)])
                                close_account = user.cash_account_id.id,
                            move_name = user.partner_id.name.upper() + payment_method + report["Code"] + \
                                        ' %s/%s ' % (count + 1, len(resp_exp))
                            line_name = user.partner_id.name.upper()
                            analytic_account_id = user.analytic_account_id.id if user.analytic_account_id else False
                            # if the expense is not from the past month or the current one, put the last day of the past month
                            if int(expense["Date"][5:7]) == datetime.now().month \
                                    or int(expense["Date"][5:7]) == (datetime.now() - timedelta(days=30)).month:
                                exp_date = expense["Date"]
                            else:
                                # This gets the last day of the past month
                                exp_date_year = (datetime.now() - timedelta(days=30)).year
                                exp_date_month = (datetime.now() - timedelta(days=30)).month
                                exp_date_day = calendar.monthrange(exp_date_year, exp_date_month)[1]
                                exp_date = "%i-%i-%i" % (exp_date_year, exp_date_month, exp_date_day)         

                            # Create the move
                            move = self.env['account.move'].create({
                                'ref': move_name,
                                'journal_id': journal.id
                            })
                            account = expense["Category"]["Account"]
                            account_id = self.env['account.account'].search([('code', '=', account),
                                                                             ('company_id', '=', self.env.user.company_id.id)])
                            partner_id = None
                            if expense["CustomFields"] and country_code == 'IT':
                                if 5480 in [cf['Id'] for cf in expense["CustomFields"]]:
                                    # 5480 id of the field 'fattura' in Captio Italy
                                    i_field = [cf['Id'] for cf in expense["CustomFields"]].index(5480)
                                    if eval(expense["CustomFields"][i_field]["Value"].capitalize()):
                                        # Italy Supplier Account
                                        account_id = self.env['account.account'].search([('code', '=', '250100')])
                                        if expense["Merchant"]:
                                            partner_id = self.env['res.partner'].search([('name', 'ilike', expense["Merchant"].split(' ')[0]),
                                                                                         ('supplier', '=', True)])

                            exp_vals.append({'name': line_name,
                                             'move_id': move.id,
                                             'account_id': account_id.id,
                                             'analytic_account_id': analytic_account_id,
                                             'date': exp_date,
                                             'debit': expense["FinalAmount"]["Value"],
                                             'credit': 0,
                                             'partner_id': partner_id or None})

                            exp_vals.append({'name': line_name,
                                             'move_id': move.id,
                                             'account_id': close_account,
                                             'debit': 0,
                                             'credit': expense["FinalAmount"]["Value"]})

                            move.line_ids = [(0, 0, x) for x in exp_vals]
                            move.move_type = 'other'
                            move.post()

        company.captio_last_date = datetime.now()
