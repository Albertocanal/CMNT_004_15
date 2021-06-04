from odoo import models, fields, api, _
from sp_api.api import Orders, Reports
from sp_api.base import Marketplaces
from datetime import datetime, timedelta
from sp_api.base.exceptions import SellingApiException, SellingApiRequestThrottledException
from odoo.exceptions import UserError
import time
import xml.etree.ElementTree as ET
import re
from dateutil.parser import parse


class AmazonSettlement(models.Model):
    _name = 'amazon.settlement'

    _order = "end_date desc"

    name = fields.Char()
    start_date = fields.Date()
    end_date = fields.Date()
    deposit_date = fields.Date()
    amazon_report_document = fields.Char()
    total_amount = fields.Monetary(currency_field='currency_id')
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company', required=True, readonly=True,
        default=lambda self: self._default_company_id())
    company_currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='company_id.currency_id',
        string='Company Currency',
        store=True, readonly=True)

    @api.model
    def _default_company_id(self):
        return self.env['res.company']._company_default_get()

    total_amount_company_currency = fields.Monetary(currency_field='company_currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        readonly=True,
        default=lambda self: self.env.user.company_id.currency_id.id
    )
    line_ids = fields.One2many('amazon.settlement.line', 'settlement_id')

    marketplace_id = fields.Many2one('amazon.marketplace', related="line_ids.marketplace_id")

    move_id = fields.Many2one('account.move')
    move_refund_id = fields.Many2one('account.move')

    @api.multi
    @api.depends("line_ids", "line_ids.state")
    def _compute_state(self):
        for settlement in self:
            line_states = [x.state == 'reconciled' or x.type in ['Order', 'Refund'] for x in settlement.line_ids]
            if all(line_states):
                settlement.state = 'done'
            elif any(line_states):
                settlement.state = 'partially_reconciled'
            else:
                settlement.state = 'read'

    state = fields.Selection([('read', 'Read'), ('partially_reconciled', 'Partially Reconciled'), ('done', 'Done')],
                             string='Status', readonly=True, copy=False,
                             index=True, track_visibility='onchange', store=True, compute="_compute_state")

    @api.multi
    def reconcile_all(self):
        for settlement in self:
            lines_orders = settlement.line_ids.filtered(lambda l: l.type == 'Order' and l.state != 'reconciled')
            lines_orders.reconcile_order_lines()
            lines_refund = settlement.line_ids.filtered(lambda l: l.type == 'Refund' and l.state != 'reconciled')
            lines_refund.reconcile_refund_lines()

    def cron_reconcile_amazon_invoices(self, created_since=False, force_date=False):
        amazon_time_rate_limit = float(self.env['ir.config_parameter'].sudo().get_param('amazon.time.rate.limit'))
        credentials = self.env['amazon.sale.order']._get_credentials()
        reports_obj = Reports(marketplace=Marketplaces.ES, credentials=credentials)
        if not created_since:
            created_since = (datetime.utcnow() - timedelta(days=14)).isoformat()
        reports_next_token = True
        while reports_next_token:
            if isinstance(reports_next_token, bool):
                reports_answer = reports_obj.get_reports(reportTypes=['GET_V2_SETTLEMENT_REPORT_DATA_XML'],
                                                         createdSince=created_since, pageSize=10)
                reports = reports_answer.payload
                reports_next_token = reports_answer.next_token
            else:
                reports_answer = reports_obj.get_reports(nextToken=reports_next_token)
                reports = reports_answer.payload
                reports_next_token = reports_answer.next_token
            for report in reports:
                read = False
                while not read:
                    try:
                        last_report_document = reports_obj.get_report_document(report.get('reportDocumentId'),
                                                                               decrypt=True).payload
                        read = True
                    except SellingApiRequestThrottledException:
                        time.sleep(amazon_time_rate_limit)
                        read = False
                    except SellingApiException as e:
                        raise UserError(_("Amazon API Error. Report %s. '%s' \n") % (report.name, e))
                document = last_report_document.get('document')
                document = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', document)
                root = ET.fromstring(document)
                settlement_data = root.find('./Message/SettlementReport/SettlementData')
                """ <SettlementData>
                        <AmazonSettlementID>12343546718237647</AmazonSettlementID>
                        <TotalAmount currency="EUR">34.37</TotalAmount>
                        <StartDate>2021-04-29T09:43:19+00:00</StartDate>
                        <EndDate>2021-05-13T09:35:05+00:00</EndDate>
                        <DepositDate>2021-05-15T09:35:05+00:00</DepositDate>
                    </SettlementData>"""
                if force_date:
                    date = datetime.strftime(parse(settlement_data[3].text), '%Y-%m-%d')
                    limit_date = datetime.strftime(parse(created_since), '%Y-%m-%d')
                    if date < limit_date:
                        continue
                name = settlement_data[0].text
                if self.env['amazon.settlement'].search([('name', 'ilike', name)]):
                    continue
                vals = {'name': name,
                        'start_date': settlement_data[2].text,
                        'end_date': settlement_data[3].text,
                        'deposit_date': settlement_data[4].text,
                        'amazon_report_document': report.get('reportDocumentId'),
                        'total_amount': float(settlement_data[1].text),
                        'currency_id': self.env['res.currency'].search(
                            [('name', '=', settlement_data[1].attrib.get('currency'))]).id}

                settlement = self.create(vals)

                rate = settlement.currency_id.with_context(date=settlement.deposit_date)._get_conversion_rate(
                    settlement.company_currency_id,
                    settlement.currency_id)
                if rate:
                    settlement.total_amount_company_currency = settlement.total_amount / rate
                else:
                    settlement.total_amount_company_currency = settlement.total_amount
                for order in root.iter('Order'):
                    settlement.parse_order_and_refund(order)
                for refund in root.iter('Refund'):
                    settlement.parse_order_and_refund(refund)
                for transaction in root.iter('OtherTransaction'):
                    if transaction[0].tag == 'AmazonOrderID':
                        line_vals = {'type': transaction.tag,
                                     'amazon_order_name': transaction[0].text,
                                     'amazon_order_id': self.env['amazon.sale.order'].search(
                                         [('name', 'ilike', transaction[0].text)]).id,
                                     'transaction_type': transaction[1].text,
                                     'transaction_name': transaction[2].text,
                                     'posted_date': transaction[3].text,
                                     'currency_id': self.env[
                                         'res.currency'].search(
                                         [('name', '=',
                                           transaction[4].attrib.get(
                                               'currency'))]).id,
                                     'amount': float(transaction[4].text),
                                     'settlement_id': settlement.id}
                    else:
                        line_vals = {'type': transaction.tag,
                                     'transaction_type': transaction[0].text,
                                     'transaction_name': transaction[1].text,
                                     'posted_date': transaction[2].text,
                                     'currency_id': self.env[
                                         'res.currency'].search(
                                         [('name', '=',
                                           transaction[3].attrib.get(
                                               'currency'))]).id,
                                     'amount': float(transaction[3].text),
                                     'settlement_id': settlement.id}
                    line = self.env['amazon.settlement.line'].create(line_vals)
                    for item in transaction.iter('OtherTransactionItem'):
                        self.env['amazon.settlement.item'].create({'sku': item[0].text,
                                                                   'qty': float(item[1].text),
                                                                   'amount': float(item[2].text),
                                                                   'currency_id': self.env[
                                                                       'res.currency'].search(
                                                                       [('name', '=',
                                                                         item[2].attrib.get(
                                                                             'currency'))]).id,
                                                                   'line_id': line.id})
                for advertising_transaction in root.iter('AdvertisingTransactionDetails'):
                    line_vals = {
                        'type': 'AdvertisingTransactionDetails',
                        'settlement_id': settlement.id,
                        'transaction_type': advertising_transaction[0].text,
                        'posted_date': advertising_transaction[1].text,
                        'invoice_name': advertising_transaction[2].text,
                        'base_amount': float(advertising_transaction[3].text),
                        'currency_id': self.env[
                            'res.currency'].search(
                            [('name', '=',
                              advertising_transaction[3].attrib.get(
                                  'currency'))]).id,
                    }
                    if line_vals.get('base_amount') == float(advertising_transaction[4].text):
                        line_vals.update({'amount': float(advertising_transaction[4].text)})
                    else:
                        line_vals.update({'tax_amount': float(advertising_transaction[4].text),
                                          'amount': float(advertising_transaction[5].text)})
                    self.env['amazon.settlement.line'].create(line_vals)
                settlement.reconcile()

    def parse_order_and_refund(self, parse_obj):
        if parse_obj.tag == 'Order':
            line_type = 'Order'
            item_name = 'Item'
        else:
            line_type = 'Refund'
            item_name = 'AdjustedItem'
        if parse_obj[1].tag == 'MerchantOrderID':
            cont = 2
        else:
            cont = 1
        line_vals = {'type': line_type,
                     'amazon_order_name': parse_obj[0].text,
                     'amazon_order_id': self.env['amazon.sale.order'].search(
                         [('name', 'ilike', parse_obj[0].text)]).id,
                     'merchant_order_id': parse_obj[1].text if cont == 2 else False,
                     'shipment_id': parse_obj[cont].text if line_type == 'Order' else False,
                     'adjustment_id': parse_obj[cont].text if line_type == 'Refund' else False,
                     'marketplace_id': self.env['amazon.marketplace'].search(
                         [('amazon_name', 'ilike', parse_obj[cont + 1].text)]).id,
                     'fulfillment': parse_obj[cont + 2][0].text,
                     'posted_date': parse_obj[cont + 2][1].text,
                     'settlement_id': self.id}
        line = self.env['amazon.settlement.line'].create(line_vals)
        for item_p in parse_obj[cont + 2].iter(item_name):
            item_vals = {'amazon_order_item_code': item_p[0].text,
                         'sku': item_p[1].text if line_type == 'Order' else item_p[2].text,
                         'qty': float(item_p[2].text) if line.type == 'Order' else False,
                         'line_id': line.id}
            item = self.env['amazon.settlement.item'].create(item_vals)
            for item_price in item_p[3]:
                item.parse_item(item_price, 'price')

            if len(item_p) > 4:
                for item_fee in item_p[4]:
                    item.parse_item(item_fee, 'fee')
                if len(item_p) > 5:
                    for cont in range(5, len(item_p)):
                        item.parse_item(item_p[cont], 'promotion')
        return line

    @api.multi
    def reconcile(self):
        amazon_max_difference_allowed = float(
            self.env['ir.config_parameter'].sudo().get_param('amazon.max.difference.allowed'))
        for settlement in self:
            line_order_ids = settlement.line_ids.filtered(lambda l: l.type == 'Order')
            if line_order_ids:
                settlement._reconcile_amazon_settlement_lines(line_order_ids, amazon_max_difference_allowed)
            line_refund_ids = settlement.line_ids.filtered(lambda l: l.type == 'Refund')
            if line_refund_ids:
                settlement._reconcile_amazon_settlement_lines(line_refund_ids, amazon_max_difference_allowed,
                                                              refund_mode=True)

    def _reconcile_amazon_settlement_lines(self, line_order_ids, amazon_max_difference_allowed, refund_mode=False):
        lines_to_reconcile = self.env['amazon.settlement.line']
        total_amount = 0
        states = ['cancel']
        lines_with_products = {}
        if not refund_mode:
            states += ['done']
        for line in line_order_ids:
            amazon_invoice = line.amazon_order_id.invoice_deposits.filtered(
                lambda i: i.state not in states and i.type != 'out_refund')
            theoretical_amount = 0
            if amazon_invoice:
                if refund_mode:
                    for item in line.items_ids:
                        product = self.env['amazon.sale.order.line'].search(
                            ['&', '|', ('product_seller_sku', '=', item.sku),
                             ('order_item', '=', item.amazon_order_item_code),
                             ('order_id', '=', line.amazon_order_id.id),
                             ]).mapped('product_id')
                        item_val = {}
                        if product:
                            invoice_line = amazon_invoice.invoice_line_ids.filtered(
                                lambda il: il.product_id == product[0])
                            if invoice_line:
                                theoretical_amount += invoice_line.price_total / invoice_line.quantity
                                item_val = {'product_id': product, 'invoice_line': invoice_line[0]}
                        if item_val:
                            if line.id in lines_with_products.keys():
                                lines_with_products[line.id].append(item_val)
                            else:
                                lines_with_products[line.id] = [item_val]
                else:
                    theoretical_amount = sum(amazon_invoice.mapped('amount_total'))
            rate = line.settlement_id.currency_id.with_context(
                date=line.posted_date)._get_conversion_rate(
                line.settlement_id.company_currency_id,
                line.settlement_id.currency_id)
            positive_events = abs(line.amount_items_positive_events) / rate
            if abs(theoretical_amount) - positive_events <= amazon_max_difference_allowed:
                lines_to_reconcile |= line
            else:
                line.error = _('Total amount != Theoretical total amount (%f-%f)\n') % (
                    abs(theoretical_amount), positive_events)
            total_amount += theoretical_amount if theoretical_amount else positive_events
        journal_id = self.env['account.journal'].search([('code', '=', 'AMAZ'), ('name', '=', 'Amazon')])
        vals = {'journal_id': journal_id.id,
                'date': self.deposit_date
                }
        if refund_mode:
            vals.update({'ref': "Pagos desde web Amazon"})
        else:
            vals.update({'ref': "Devoluciones desde web Amazon"})
        move = self.env['account.move'].create(vals)
        if refund_mode:
            self.move_refund_id = move
        else:
            self.move_id = move
        account_430 = self.env['account.account'].search(
            [('code', '=', '43000000'), ('company_id', '=', self.env.user.company_id.id)])
        account_trans = self.marketplace_id.account_id if self.marketplace_id else self.line_ids[
            0].marketplace_id.account_id
        partner_id = self.env['res.partner'].search([('name', '=', 'Ventas Amazon')])
        values = {'partner_id': partner_id.id,
                  'journal_id': journal_id.id,
                  'date': self.deposit_date,
                  'date_maturity': self.deposit_date,
                  'company_id': self.env.user.company_id.id,
                  'move_id': move.id}
        if refund_mode:
            values_430 = {
                'name': "Devoluciones ventas",
                'account_id': account_430.id,
                'debit': total_amount,
            }
            values_trans = {
                'name': "Cobro Amazon",
                'account_id': account_trans.id,
                'credit': total_amount,
            }
        else:
            values_430 = {
                'name': "Ventas no facturadas",
                'account_id': account_430.id,
                'credit': total_amount,
            }

            values_trans = {
                'name': "Pago Amazon",
                'account_id': account_trans.id,
                'debit': total_amount,
            }
        values_430.update(values)
        values_trans.update(values)
        move_lines = [values_trans, values_430]
        move.line_ids = [(0, 0, x) for x in move_lines]
        move.post()
        if refund_mode:
            lines_to_reconcile.reconcile_refund_lines(lines_with_products)
        else:
            lines_to_reconcile.reconcile_order_lines()


class AmazonSettlementLine(models.Model):
    _name = 'amazon.settlement.line'

    type = fields.Selection(
        selection=[('Order', 'Order'),
                   ('Refund', 'Refund'),
                   ('OtherTransaction', 'OtherTransaction'),
                   ('AdvertisingTransactionDetails', 'AdvertisingTransactionDetails')])

    amazon_order_name = fields.Text()
    amazon_order_id = fields.Many2one('amazon.sale.order')
    settlement_id = fields.Many2one('amazon.settlement')
    merchant_order_id = fields.Char()
    shipment_id = fields.Char()
    adjustment_id = fields.Char()
    marketplace_id = fields.Many2one("amazon.marketplace")
    fulfillment = fields.Char()
    posted_date = fields.Date()
    items_ids = fields.One2many("amazon.settlement.item", 'line_id')
    transaction_name = fields.Char()
    transaction_type = fields.Char()
    amount = fields.Monetary('Other Transaction Amount')
    currency_id = fields.Many2one(
        'res.currency',
        readonly=True,
        default=lambda self: self.settlement_id.currency_id.id)
    invoice_name = fields.Char()
    amount_items = fields.Monetary(compute="_compute_items_value")
    amount_items_positive_events = fields.Monetary(compute="_compute_items_positive_items")
    # tax_amount and base_amount only for AdvertisingTransactionDetails type
    tax_amount = fields.Monetary('Advertising Transaction Tax Amount')
    base_amount = fields.Monetary('Advertising Transaction Base Amount')
    state = fields.Selection([('read', 'Read'), ('reconciled', 'Reconciled')], string='Status', readonly=True,
                             copy=False,
                             index=True, track_visibility='onchange', default='read')
    refund_invoice_id = fields.Many2one('account.invoice')
    error = fields.Char()

    @api.multi
    def _compute_items_value(self):
        for line in self:
            if line.type in ['Order', 'Refund']:
                line.amount_items = sum(line.items_ids.mapped('amount')) + sum(
                    line.items_ids.mapped('item_event_ids.amount'))
            else:
                line.amount_items = 0

    @api.multi
    def _compute_items_positive_items(self):
        for line in self:
            if line.type in ['Order', 'Refund']:
                line.amount_items_positive_events = sum(
                    line.items_ids.mapped('item_event_ids').filtered(lambda i: i.type != 'fee').mapped('amount'))
            else:
                line.amount_items_positive_events = 0

    @api.multi
    def make_refund_invoice(self, invoice):
        header_vals = {
            'partner_id': invoice.partner_id.id,
            'fiscal_position_id':
                invoice.fiscal_position_id.id,
            'date_invoice': datetime.now().strftime('%Y-%m-%d'),
            'journal_id': invoice.journal_id.id,
            'account_id':
                invoice.partner_id.property_account_receivable_id.id,
            'currency_id':
                invoice.currency_id.id,
            'company_id': invoice.company_id.id,
            'user_id': self.env.user.id,
            'type': 'out_refund',
            'payment_term_id': False,
            'payment_mode_id':
                invoice.payment_mode_id.id,
            'name': invoice.name,
            'amazon_order': invoice.amazon_order.id,
        }
        return self.env['account.invoice'].create(header_vals)

    @api.multi
    def reconcile_refund_lines(self, line_with_products={}):
        for line in self:
            if not line.amazon_order_id:
                am_o = self.env['amazon.sale.order'].search(
                    [('name', 'ilike', line.amazon_order_name)])
                if am_o:
                    line.amazon_order_id = am_o
            if not line.refund_invoice_id:
                if line_with_products.get(line.id, False):
                    elements = line_with_products[line.id]
                    refund = self.make_refund_invoice(elements[0].get('invoice_line').invoice_id)
                    line.refund_invoice_id = refund
                    for e in elements:
                        product = e.get('product_id')
                        invoice_line = e.get('invoice_line')
                        vals = {
                            'invoice_id': refund.id,
                            'name': invoice_line.name,
                            'product_id': product.id,
                            'account_id': invoice_line.account_id.id,
                            'quantity': 1,
                            'price_unit': invoice_line.price_unit,
                            'cost_unit': invoice_line.cost_unit,
                            'discount': invoice_line.discount,
                            'account_analytic_id': False,
                            'invoice_line_tax_ids': [(6, 0, invoice_line.invoice_line_tax_ids.ids)]
                        }
                        self.env['account.invoice.line'].create(vals)
                    refund.compute_taxes()
                    refund.action_invoice_open()
                else:
                    amazon_invoice = line.amazon_order_id.invoice_deposits.filtered(
                        lambda i: i.state != 'cancel' and i.type != 'out_refund')
                    if amazon_invoice:
                        refund = self.make_refund_invoice(amazon_invoice)
                        line.refund_invoice_id = refund
                        for item in line.items_ids:
                            product = self.env['amazon.sale.order.line'].search(
                                ['&', '|', ('product_seller_sku', '=', item.sku),
                                 ('order_item', '=', item.amazon_order_item_code),
                                 ('order_id', '=', line.amazon_order_id.id),
                                 ]).mapped('product_id')
                            invoice_line = amazon_invoice.invoice_line_ids.filtered(
                                lambda il: il.product_id == product[0])
                            if invoice_line:
                                vals = {
                                    'invoice_id': refund.id,
                                    'name': invoice_line[0].name,
                                    'product_id': product.id,
                                    'account_id': invoice_line.account_id.id,
                                    'quantity': 1,
                                    'price_unit': invoice_line[0].price_unit,
                                    'cost_unit': invoice_line[0].cost_unit,
                                    'discount': invoice_line[0].discount,
                                    'account_analytic_id': False,
                                    'invoice_line_tax_ids': [(6, 0, invoice_line[0].invoice_line_tax_ids.ids)]
                                }
                                self.env['account.invoice.line'].create(vals)
                        refund.compute_taxes()
                        refund.action_invoice_open()

            if line.refund_invoice_id:
                move_line_id = line.refund_invoice_id.move_id.line_ids.filtered(
                    lambda aml: aml.account_id.code == '43000000')
                if move_line_id:
                    moves = line.settlement_id.move_refund_id.line_ids.filtered(
                        lambda ml: ml.account_id.code == '43000000' and ml.debit > 0) + move_line_id
                    move_lines_filtered = moves.filtered(lambda aml: not aml.reconciled)
                    move_lines_filtered.with_context(skip_full_reconcile_check='amount_currency_excluded').reconcile()
                    moves.force_full_reconcile()
                    line.state = "reconciled"

    @api.multi
    def reconcile_order_lines(self):
        for line in self:
            if not line.amazon_order_id:
                am_o = self.env['amazon.sale.order'].search(
                    [('name', 'ilike', line.amazon_order_name)])
                if am_o:
                    line.amazon_order_id = am_o
            if line.amazon_order_id:
                move_line_id = self.env['account.move.line'].search(
                    ['&', '|', ('name', 'ilike', line.amazon_order_name),
                     ('invoice_id', 'in',
                      line.amazon_order_id.invoice_deposits.filtered(lambda i: i.state not in ['cancel', 'done']).ids),
                     ('account_id.code', '=', '43000000')])
            else:
                move_line_id = self.env['account.move.line'].search(
                    [('name', 'ilike', line.amazon_order_name), ('account_id.code', '=', '43000000')])
            if move_line_id:
                moves = line.settlement_id.move_id.line_ids.filtered(
                    lambda ml: ml.account_id.code == '43000000') + move_line_id
                move_lines_filtered = moves.filtered(lambda aml: not aml.reconciled)
                move_lines_filtered.with_context(skip_full_reconcile_check='amount_currency_excluded').reconcile()
                moves.force_full_reconcile()
                line.state = "reconciled"


class AmazonSettlementItem(models.Model):
    _name = 'amazon.settlement.item'

    amazon_order_item_code = fields.Char()
    sku = fields.Char()
    qty = fields.Float()
    line_id = fields.Many2one('amazon.settlement.line')
    item_event_ids = fields.One2many('amazon.settlement.item.event', 'item_id')
    amount = fields.Monetary()
    currency_id = fields.Many2one(
        'res.currency',
        readonly=True,
        default=lambda self: self.line_id.settlement_id.currency_id.id)

    def parse_item(self, event, type):
        name_index = 0 if type != 'promotion' else 1

        self.env['amazon.settlement.item.event'].create(
            {'name': event[name_index].text,
             'type': type,
             'amount': float(event[name_index + 1].text),
             'currency_id': self.env[
                 'res.currency'].search(
                 [('name', '=',
                   event[name_index + 1].attrib.get(
                       'currency'))]).id,
             'item_id': self.id,
             'merchant_promotion': event[
                 0].text if type == 'promotion' else False})


class AmazonSettlementItemEvent(models.Model):
    _name = 'amazon.settlement.item.event'

    name = fields.Char()
    type = fields.Selection([("fee", "Fee"), ("price", "Price"), ("promotion", "Promotion")])
    amount = fields.Monetary()
    item_id = fields.Many2one('amazon.settlement.item')
    currency_id = fields.Many2one(
        'res.currency',
        readonly=True,
        default=lambda self: self.item_id.line_id.settlement_id.currency_id.id)
    merchant_promotion = fields.Char()
