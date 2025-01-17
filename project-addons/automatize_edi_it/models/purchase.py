# Copyright 2019 Omar Castiñeira, Comunitea Servicios Tecnológicos S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models, fields, api, exceptions, _
import odoorpc


class PurchaseOrderLine(models.Model):

    _inherit = "purchase.order.line"

    @api.multi
    def _prepare_stock_moves(self, picking):
        res = super()._prepare_stock_moves(picking)
        if self.order_id.picking_type_id.force_location:
            for move_dict in res:
                move_dict['location_id'] = \
                    self.order_id.picking_type_id.default_location_src_id.id
        return res


class ProrementRule(models.Model):

    _inherit = "procurement.rule"

    def _prepare_purchase_order(self, product_id, product_qty, product_uom,
                                origin, values, partner):
        res = super()._prepare_purchase_order(product_id, product_qty,
                                              product_uom, origin, values,
                                              partner)
        if partner.automatice_purchases:
            res['force_confirm'] = True
            res['date_planned'] = fields.Datetime.now()
        return res


class PurchaseOrder(models.Model):

    _inherit = "purchase.order"

    @api.depends('amount_to_invoice_es')
    @api.multi
    def _get_to_invoice_diff(self):
        for order in self:
            order.diff_to_invoice = order.amount_to_invoice_es - order.amount_to_invoice_it

    @api.multi
    def _get_amt_to_invoice(self):
        for order in self:
            order.amount_to_invoice_it = sum([l.qty_received * l.price_unit for l in order.order_line])

    force_confirm = fields.Boolean()
    amount_to_invoice_es = fields.Monetary()
    diff_to_invoice = fields.Monetary(compute='_get_to_invoice_diff', store=True)
    es_sale_order = fields.Char('ES Sale')
    amount_to_invoice_it = fields.Monetary('To Invoice', compute='_get_amt_to_invoice', store=False)

    @api.model
    def _check_picking_to_process(self):
        pickings_to_stock = self.env['stock.picking'].search([('picking_type_id', '=',
                                                               self.env.ref('stock.picking_type_in').id),
                                                              ('location_id', '=',
                                                               self.env.ref('automatize_edi_it.stock_location_vendor_deposit').id),
                                                              ('location_dest_id', '=',
                                                               self.env.ref('stock.stock_location_stock').id),
                                                              ('state', 'in',
                                                               ("assigned", "confirmed", "partially_available"))])
        pickings_to_stock._process_picking()

    @api.model
    def _process_purchase_order_automated(self):
        purchases = self.search([('force_confirm', '=', True),
                                 ('order_line', '!=', False),
                                 ('state', '=', 'draft')])
        for order in purchases:
            order.with_context(bypass_override=True).button_confirm()
            action = order.attach_ubl_xml_file_button()
            attachment = self.env['ir.attachment'].browse(action['res_id'])
            output_folder = self.env['base.io.folder'].\
                search([('direction', '=', 'export')], limit=1)
            if not output_folder:
                raise exceptions.UserError(_("Please create an export folder"))
            output_folder.export_file(attachment.datas, attachment.name)
            order.picking_ids._process_picking()
        self._check_picking_to_process()

    picking_type_id = fields.Many2one('stock.picking.type',
                                      default=lambda self:
                                      self.env.ref('automatize_edi_it.picking_type_receive_top_deposit'))

    def _get_qty_to_invoice_es(self, purchase_ref, odoo_es):
        amt_to_invoice = 0.0
        es_sale = None
        order_es_id = odoo_es.env['sale.order'].search([('client_order_ref', '=', purchase_ref), ('partner_id', '=', 245247)])
        if order_es_id:
            order_es = odoo_es.env['sale.order'].browse(order_es_id)
            es_sale = order_es.name
            if order_es.invoice_status == 'to invoice':
                for line in order_es.order_line:
                    amt_to_invoice += line.qty_to_invoice * line.price_unit
        return amt_to_invoice, es_sale

    def cron_check_qty_to_invoice_lx(self):
        purchases = self.search([('invoice_status', '=', 'to invoice')])

        if purchases:
            # get the server
            server = self.env['base.synchro.server'].search([('name', '=', 'Visiotech')])
            # Prepare the connection to the server
            odoo_es = odoorpc.ODOO(server.server_url, port=server.server_port)
            # Login
            odoo_es.login(server.server_db, server.login, server.password)

            for purchase in purchases:
                if purchase.amount_total != purchase.amount_to_invoice_es:
                    purchase.amount_to_invoice_es, purchase.es_sale_order = self._get_qty_to_invoice_es(purchase.name, odoo_es)

            odoo_es.logout()



