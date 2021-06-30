from odoo import models, fields, api, _
from sp_api.api import Orders, Reports
from sp_api.base import Marketplaces
from datetime import datetime, timedelta
from sp_api.base.exceptions import SellingApiException, SellingApiRequestThrottledException
from odoo.exceptions import UserError
import time


class AmazonSaleOrder(models.Model):
    _name = 'amazon.sale.order'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char("Amazon Order Id")
    order_line = fields.One2many('amazon.sale.order.line', 'order_id', string='Order Lines', readonly=True)
    deposits = fields.One2many("stock.deposit", 'amazon_order_id')
    sale_deposits = fields.One2many("sale.order", compute='_compute_count')
    invoice_deposits = fields.One2many("account.invoice", compute='_compute_count')
    deposits_count = fields.Integer(compute='_compute_count', default=0)
    sale_deposits_count = fields.Integer(compute='_compute_count', default=0)
    invoice_deposits_count = fields.Integer(compute='_compute_count', default=0)
    state = fields.Selection([
        ('error', 'Error'),
        ('warning', 'Warning'),
        ('read', 'Read'),
        ('sale_created', 'Sale created'),
        ('invoice_created', 'Invoice created'),
        ('invoice_open', 'Invoice open')
    ], string='Status', readonly=True, copy=False, index=True, track_visibility='onchange', default='error')
    fulfillment = fields.Selection([
        ('AFN', 'Amazon'),
        ('MFN', 'Own')
    ], readonly=1)
    sales_channel = fields.Many2one("amazon.marketplace","Sales Channel")
    purchase_date = fields.Date("Purchase Date")
    partner_vat = fields.Char()
    vat_imputation_country = fields.Char()
    buyer_email = fields.Char()
    buyer_name = fields.Char()
    amazon_invoice_name = fields.Char("Amazon Invoice")
    city = fields.Char('City')
    country_id = fields.Many2one('res.country', string='Country', readonly=True)
    state_id = fields.Char()
    zip = fields.Char(string='Postal Code')

    def _compute_count(self):
        for order in self:
            if order.deposits:
                order.deposits_count = len(order.deposits)
                order.sale_deposits = order.deposits.mapped('sale_id')
                order.invoice_deposits = self.env['account.invoice'].search([('amazon_order','=',order.id)])
                order.sale_deposits_count = len(order.sale_deposits)
                order.invoice_deposits_count = len(order.invoice_deposits)

    def action_view_sales(self):
        action = self.env.ref('sale.action_quotations').read()[0]
        if len(self.sale_deposits) > 0:
            action['domain'] = [('id', 'in', self.sale_deposits.ids)]
            action['context'] = [('id', 'in', self.sale_deposits.ids)]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_view_invoices(self):
        action = self.env.ref('account.action_invoice_tree1').read()[0]
        if len(self.invoice_deposits) > 0:
            action['domain'] = [('id', 'in', self.invoice_deposits.ids)]
            action['context'] = [('id', 'in', self.invoice_deposits.ids)]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_view_deposits(self):
        action = self.env.ref('stock_deposit.action_stock_deposit').read()[0]
        if len(self.deposits) > 0:
            action['domain'] = [('id', 'in', self.deposits.ids)]
            action['context'] = [('id', 'in', self.deposits.ids)]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    @api.depends('order_line.price_total')
    def _amount_all(self):
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.order_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': amount_untaxed,
                'amount_tax': amount_tax,
                'amount_total': amount_untaxed + amount_tax,
            })

    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, readonly=True, compute='_amount_all',
                                     track_visibility='onchange')
    amount_tax = fields.Monetary(string='Taxes', store=True, readonly=True, compute='_amount_all')
    amount_total = fields.Monetary(string='Total', store=True, readonly=True, compute='_amount_all',
                                   track_visibility='always')
    theoretical_total_amount = fields.Monetary()
    theoretical_total_taxes = fields.Monetary()
    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        readonly=True,
        default=lambda self: self.env.user.company_id.currency_id.id
    )
    message_error = fields.Text()
    warning_price = fields.Boolean(default=False)

    def cron_create_amazon_sale_orders(self, data_start_time=False, data_end_time=False, marketplaces=False, only_read=False):
        amazon_time_rate_limit = float(self.env['ir.config_parameter'].sudo().get_param('amazon.time.rate.limit'))
        amazon_max_difference_allowed = float(self.env['ir.config_parameter'].sudo().get_param('amazon.max.difference.allowed'))
        credentials = self._get_credentials()
        if not data_start_time:
            data_start_time = (datetime.utcnow() - timedelta(days=1)).isoformat()
        if not data_end_time:
            data_end_time = datetime.utcnow().isoformat()
        orders_obj = Orders(marketplace=Marketplaces.ES, credentials=credentials)
        reports_obj = Reports(marketplace=Marketplaces.ES, credentials=credentials)
        if not marketplaces:
            marketplaces = self._get_marketplaces()
        try:
            report_created = reports_obj.create_report(reportType="SC_VAT_TAX_REPORT",
                                                       marketplaceIds=marketplaces,
                                                       dataStartTime=data_start_time,
                                                       dataEndTime=data_end_time).payload
        except SellingApiException as e:
            raise UserError(_("Amazon API Error. No order was created due to errors. '%s' \n") % e)
        report_state = ""
        while report_state != 'DONE':
            try:
                report = reports_obj.get_report(report_created.get('reportId')).payload
                report_state = report.get("processingStatus")
            except SellingApiRequestThrottledException:
                time.sleep(amazon_time_rate_limit)
                continue
            except SellingApiException as e:
                raise UserError(_("Amazon API Error. Report %s. '%s' \n") % (report_created.get('reportId'), e))

        report_document = reports_obj.get_report_document(report.get('reportDocumentId'), decrypt=True).payload
        document_lines = report_document.get('document').split("\n")
        headers = document_lines[0].split(',')
        orders = document_lines[1:-1]
        order_name_index = headers.index('"Order ID"')
        vat_number_index = headers.index('"Buyer Tax Registration"')
        vat_imputation_country_index = headers.index('"Buyer Tax Registration Jurisdiction"')
        order_date_index = headers.index('"Order Date"')
        amazon_invoice_index = headers.index('"VAT Invoice Number"')
        transaction_type_index = headers.index('"Transaction Type"')
        city_index = headers.index('"Ship To City"')
        state_index = headers.index('"Ship To State"')
        country_index = headers.index('"Ship To Country"')
        zip_index = headers.index('"Ship To Postal Code"')
        for order in orders:
            order = order.split(',')
            if order[transaction_type_index]=="SHIPMENT" and order[country_index] == 'ES':
                order_name = order[order_name_index]
                exist_order = self.env['amazon.sale.order'].search([('name', '=', order_name)])
                if exist_order:
                    continue
                read = False
                while not read:
                    try:
                        res_order = orders_obj.get_order_items(order_name)
                        read = True
                    except SellingApiRequestThrottledException:
                        time.sleep(amazon_time_rate_limit)
                        read = False
                    except SellingApiException as e:
                        raise UserError(_("Amazon API Error. Order %s. '%s' \n") % (order_name, e))
                new_order = res_order.payload
                if new_order:
                    amazon_order_values = {'name': order_name,
                                           'partner_vat':order[vat_number_index] or False,
                                           'vat_imputation_country':order[vat_imputation_country_index] or False,
                                           'purchase_date': order[order_date_index] or False,
                                           'amazon_invoice_name': order[amazon_invoice_index] or False,
                                           'city': order[city_index] or '',
                                           'country_id' : self.env['res.country'].search([('code','=',order[country_index])]).id,
                                           'state_id': order[state_index],
                                           'zip': order[zip_index] or ''
                                           }
                    read = False
                    while not read:
                        try:
                            order_complete = orders_obj.get_order(order_name).payload
                            read = True
                        except SellingApiRequestThrottledException:
                            time.sleep(amazon_time_rate_limit)
                            read = False
                        except SellingApiException as e:
                            raise UserError(_("Amazon API Error. Order %s. '%s' \n") % (order_name, e))
                    amazon_order_values.update({
                                               'fulfillment': order_complete.get('FulfillmentChannel',False),
                                               'sales_channel':self.env['amazon.marketplace'].search([('amazon_name','=',order_complete.get('SalesChannel',False))]).id})
                    amazon_order_values_lines = self._get_lines_values(new_order)
                    amazon_order_values.update(amazon_order_values_lines)
                    amazon_order = self.env['amazon.sale.order'].create(amazon_order_values)
                    if abs(amazon_order.amount_total - amazon_order.theoretical_total_amount) > amazon_max_difference_allowed:
                        amazon_order.message_error += _('Total amount != Theoretical total amount (%f-%f)\n') % (
                            amazon_order.amount_total, amazon_order.theoretical_total_amount)
                        amazon_order.warning_price = True
                    if (amazon_order.partner_vat and amazon_order.vat_imputation_country and amazon_order.amount_total > 400)\
                            or amazon_order.amount_tax==0:
                        read = False
                        while not read:
                            try:
                                buyer_info = orders_obj.get_order_buyer_info(order_name).payload
                                read = True
                            except SellingApiRequestThrottledException:
                                time.sleep(amazon_time_rate_limit)
                                read = False
                            except SellingApiException as e:
                                raise UserError(_("Amazon API Error. Buyer Info Request. Order %s. '%s' \n") % (order_name, e))

                        amazon_order.buyer_email = buyer_info.get('BuyerEmail',False)
                        amazon_order.buyer_name = buyer_info.get('BuyerName',False)
                        amazon_order.message_error += _(
                            'This Order requires a non simplified Invoice')
                        if amazon_order.state != 'error':
                            amazon_order.state = 'warning'
                    if amazon_order.state == 'error':
                        amazon_order.send_error_mail()
                    else:
                        if amazon_order.warning_price or amazon_order.state == 'warning':
                            amazon_order.send_error_mail()
                        if not only_read:
                            amazon_order.process_order()
    @api.multi
    def retry_order(self):
        amazon_time_rate_limit = float(self.env['ir.config_parameter'].sudo().get_param('amazon.time.rate.limit'))
        amazon_max_difference_allowed = float(self.env['ir.config_parameter'].sudo().get_param('amazon.max.difference.allowed'))
        credentials = self._get_credentials()
        for amazon_order in self:
            orders_obj = Orders(marketplace=Marketplaces.ES, credentials=credentials)
            read = False
            while not read:
                try:
                    res_order_header = orders_obj.get_order(amazon_order.name)
                    read = True
                except SellingApiRequestThrottledException:
                    time.sleep(amazon_time_rate_limit)
                    read = False
                except SellingApiException as e:
                    raise UserError(_("Amazon API Error. Order %s. '%s' \n" % (amazon_order.name, e)))

            order_header = res_order_header.payload
            amazon_order.write({'fulfillment': order_header.get('FulfillmentChannel', False),
                                'sales_channel': self.env['amazon.marketplace'].search(
                                    [('amazon_name', '=', order_header.get('SalesChannel', False))]).id,
                                'purchase_date': order_header.get('PurchaseDate', False)})
            amazon_order.message_error = ""
            read = False
            while not read:
                try:
                    res_order = orders_obj.get_order_items(amazon_order.name)
                    read = True
                except SellingApiRequestThrottledException:
                    time.sleep(amazon_time_rate_limit)
                    read = False
                except SellingApiException as e:
                    raise UserError(_("Amazon API Error. Order %s. '%s' \n" % (amazon_order.name, e)))
            order = res_order.payload
            if order:
                amazon_order.order_line.unlink()
                amazon_order_values = amazon_order._get_lines_values(order)
                amazon_order.write(amazon_order_values)
                if abs(amazon_order.amount_total - amazon_order.theoretical_total_amount) > amazon_max_difference_allowed:
                    amazon_order.message_error += _('Total amount != Theoretical total amount (%f-%f)\n') % (
                        amazon_order.amount_total, amazon_order.theoretical_total_amount)
                    amazon_order.warning_price = True
                if (amazon_order.partner_vat and amazon_order.vat_imputation_country and amazon_order.amount_total > 400) \
                        or amazon_order.amount_tax == 0:
                    amazon_order.message_error += _(
                        'This Order requires a non simplified Invoice')
                    if amazon_order.state != 'error':
                        amazon_order.state = 'warning'
                if amazon_order.state in ['error','warning'] or amazon_order.warning_price:
                    amazon_order.send_error_mail()

    def _get_marketplaces(self):
        company = self.env.user.company_id
        return company.marketplace_ids.mapped('code')

    def _get_lines_values(self, order):
        amazon_order_values = {'order_line': [],
                               'message_error': ""}
        default_currency = True
        order_total_price = 0
        order_total_taxes = 0
        for order_item in order.get('OrderItems'):
            product_qty = int(order_item.get('QuantityOrdered'))
            asin_code = order_item.get('ASIN')
            line = {'product_asin': asin_code,
                    'product_qty': product_qty,
                    'product_seller_sku':  order_item.get('SellerSKU'),
                    'order_item':  order_item.get('OrderItemId'),
            }
            product_obj = self.env['product.product'].search([('asin_code', '=', asin_code)])
            if not product_obj:
                amazon_order_values['message_error'] += _('Product with ASIN CODE %s not found\n') % asin_code
            line['product_id'] = product_obj.id
            if not order_item.get('ItemPrice', False) or not order_item.get('ItemTax', False):
                amazon_order_values['message_error'] += _('ItemPrice or ItemTax fields are empty %s\n') % asin_code
            else:
                price_total = float(order_item.get('ItemPrice').get('Amount'))
                order_total_price += price_total
                if default_currency:
                    default_currency = False
                    currency = self.env['res.currency'].search([('name', '=', order_item.get('ItemPrice').get('CurrencyCode'))])
                    if not currency:
                        amazon_order_values['message_error'] += _('There is no currency with this name or it is no activated %s\n') % order_item.get('ItemPrice').get('CurrencyCode')
                    amazon_order_values['currency_id'] = currency.id or self.env.user.company_id.currency_id.id
                taxes = float(order_item.get('ItemTax').get('Amount'))
                order_total_taxes += taxes
                price_subtotal = price_total - taxes
                if order_item.get('PromotionDiscount',False):
                    discount = float(order_item.get('PromotionDiscount').get('Amount'))
                    price_subtotal -= discount
                    order_total_price -= discount
                    line.update({'discount':discount})
                price_unit = price_subtotal / product_qty
                taxes_obj = self.env['account.tax'].search(
                    [('description', '=', 'S_IVA21B' if taxes > 0 else 'S_IVA0_IC'),
                     ('company_id', '=', self.env.user.company_id.id)])
                line.update({'price_unit': price_unit,
                             'tax_id': [(6, 0, taxes_obj.ids)]})
            amazon_order_values['order_line'].append((0, 0, line))
        amazon_order_values['theoretical_total_amount'] = order_total_price
        amazon_order_values['theoretical_total_taxes'] = order_total_taxes
        if amazon_order_values["message_error"] == "":
            amazon_order_values["state"] = "read"
        return amazon_order_values

    def _get_credentials(self):
        company = self.env.user.company_id
        return dict(
            refresh_token=company.refresh_token,
            lwa_app_id=company.lwa_app_id,
            lwa_client_secret=company.lwa_client_secret,
            aws_secret_key=company.aws_secret_key,
            aws_access_key=company.aws_access_key,
            role_arn=company.role_arn,
        )

    def send_error_mail(self):
        template = self.env.ref('amazon_connector.send_mail_errors_amazon')
        if self.warning_price:
            context = {'message_warning': 'The order has been processed but the invoice is in draft status.'}
            template.with_context(context).send_mail(self.id)
        elif self.state=='warning':
            context = {'message_warning': 'The order has been processed but the invoice has not been created.'}
            template.with_context(context).send_mail(self.id)
        else:
            template.send_mail(self.id)

    @api.multi
    def process_order(self, orders_obj=False):
        for order in self:
            if order.fulfillment == 'MFN':
                print('nada que hacer de momento')
                # if not orders_obj:
                #     credentials = self._get_credentials()
                #     orders_obj = Orders(marketplace=Marketplaces.ES, credentials=credentials)
                # TODO Crear Pedido con cliente ventas Amazon y poner dirección de envío
                # res_address = orders_obj.get_order_address(order.get('AmazonOrderId'))
                # address = res_address.payload
                # country = self.env['res.country'].search([('code', '=', address.get('Country'))])
                # partner = self.env['res.partner'].search([('name', '=', 'Ventas Amazon')])
                # shipping_vals = {"name": address.get('Name'),
                #                  "active": False,
                #                  "dropship": True,
                #                  "street": address.get('AddressLine1', False),
                #                  "city": address.get('City', False),
                #                  "zip": address.get('PostalCode', False),
                #                  "country_id": country.id,
                #                  "parent_id": partner.id,
                #                  "type": "delivery",
                #                  "email": address.get('name', False),
                #                  "street2": address.get('AddressLine1', False),
                #                  "phone": address.get('Phone', False),
                #                  "customer": True,
                #                  "is_company": False,
                #                  "delivery_type": "shipping"}
                #
                # partner_shipping_id = self.env['res.partner'].create(shipping_vals)
                # order_vals = {
                #     'state': 'reserve',
                #     'order_line': [],
                #     'partner_id': partner.id,
                #     'partner_shipping_id': partner_shipping_id.id,
                #     'no_promos': True
                # }
                # sale_order = self.env['sale.order'].create({order_vals})
                # sale_order.onchange_partner_id()
                # sale_order.action_confirm()
            else:
                # Buscar el depósito, crear la venta, crear factura, ajustar precio de la factura generada con el de venta en amazon y validarla
                deposits = self.env['stock.deposit']
                if not order.deposits:
                    for line in order.order_line:
                        cont = 0
                        max = line.product_qty
                        deposits_part = self.env['stock.deposit'].search(
                            [('partner_id.name', '=', 'Ventas Amazon'),
                             ('state', '=', 'draft'),
                             ('product_id', '=', line.product_id.id)],
                            order='delivery_date asc')
                        for deposit in deposits_part:
                            if cont + deposit.product_uom_qty < max:
                                cont += deposit.product_uom_qty
                                deposits += deposit
                            elif cont + deposit.product_uom_qty == max:
                                cont += deposit.product_uom_qty
                                deposits += deposit
                                break
                            else:
                                qty_to_sale = max - cont
                                new_deposit = deposit.copy()
                                new_deposit.write({'product_uom_qty': deposit.product_uom_qty - qty_to_sale})
                                deposit.write({'product_uom_qty': qty_to_sale})
                                deposits += deposit
                                break
                    if deposits:
                        order.deposits = [(6, 0, deposits.ids)]
                        deposits.sale()
                        order.state = "sale_created"
                        if (order.partner_vat and order.vat_imputation_country and order.amount_total > 400) \
                                or order.amount_tax == 0:
                            order.state = 'warning'
                        else:
                            invoices_ids = deposits.create_invoice()
                            order.state = "invoice_created"
                            invoices = self.env['account.invoice'].browse(invoices_ids)
                            if len(invoices)>1:
                                allinvoices = invoices.do_merge(keep_references=False)
                                invoices = self.env['account.invoice'].browse(list(allinvoices))

                            if not order.warning_price:
                                invoices.action_invoice_open()
                                order.state = 'invoice_open'

                    else:
                        self.env.user.notify_warning(message=_("There are no deposit for this order"))

    def mark_to_done(self):
        if self.invoice_deposits:
            states = self.invoice_deposits.mapped('state')
            if all([x=='draft' for x in states]):
                self.state='invoice_created'
            else:
                self.state='invoice_open'
        else:
            raise UserError(_("There aren't any invoices linked to this Amazon order"))

class AmazonSaleOrderLine(models.Model):
    _name = 'amazon.sale.order.line'

    product_asin = fields.Char(required=True)
    product_seller_sku = fields.Char()
    order_item = fields.Char()
    product_id = fields.Many2one('product.product')
    product_qty = fields.Float()
    price_unit = fields.Float()
    discount = fields.Monetary()
    price_tax = fields.Monetary(compute='_compute_amount', store=True)
    price_total = fields.Monetary(compute='_compute_amount', store=True)
    price_subtotal = fields.Monetary(compute='_compute_amount', store=True)
    order_id = fields.Many2one('amazon.sale.order', string='Order Reference', required=True, ondelete='cascade',
                               index=True, copy=False)
    tax_id = fields.Many2many('account.tax')

    currency_id = fields.Many2one(
        'res.currency',
        required=True,
        readonly=True,
        related='order_id.currency_id'
    )

    @api.depends('product_qty', 'price_unit', 'tax_id', 'product_id')
    def _compute_amount(self):
        for line in self:
            taxes = line.tax_id.compute_all(line.price_unit, line.currency_id,
                                            line.product_qty,
                                            product=line.product_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })


class AmazonMarketplace(models.Model):
    _name = 'amazon.marketplace'

    name = fields.Char(translate=True)
    code = fields.Char()
    amazon_name = fields.Char()
    account_id = fields.Many2one("account.account")
