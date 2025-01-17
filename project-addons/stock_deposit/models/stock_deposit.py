##############################################################################
#
#    Author: Santi Argüeso
#    Copyright 2014 Pexego Sistemas Informáticos S.L.
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from odoo import models, fields, api, exceptions, _
from datetime import datetime
from odoo.exceptions import UserError


class StockDeposit(models.Model):
    _name = 'stock.deposit'
    _description = "Deposits"
    _inherit = ['mail.thread']

    product_id = fields.Many2one(string='Product',
                                 related='move_id.product_id',
                                 store=True, readonly=True)
    product_uom_qty = fields.Float('Product qty',
                                   related='move_id.product_uom_qty',
                                   store=True, readonly=True)
    product_uom = fields.Many2one(related='move_id.product_uom',
                                  string='Uom',
                                  store=True,
                                  readonly=True)
    invoice_id = fields.Many2one('account.invoice', 'Invoice')
    move_id = fields.Many2one('stock.move', 'Deposit Move', required=True,
                              readonly=True, ondelete='cascade', index=1)
    picking_id = fields.Many2one(related='move_id.picking_id',
                                 string='Picking',
                                 store=True,
                                 readonly=True)
    partner_id = fields.Many2one(related='move_id.partner_id',
                                 string='Destination Address',
                                 store=True,
                                 readonly=True)
    sale_id = fields.Many2one(related='move_id.sale_line_id.order_id',
                              string='Sale',
                              store=True,
                              readonly=True)
    delivery_date = fields.Datetime('Date of Transfer')
    return_date = fields.Date('Return date')
    company_id = fields.Many2one(related='move_id.company_id',
                                 string='Date of Transfer',
                                 store=True,
                                 readonly=True)
    state = fields.Selection([('draft', 'Draft'), ('sale', 'Sale'),
                              ('returned', 'Returned'),
                              ('invoiced', 'Invoiced'),
                              ('loss', 'Loss')], 'State',
                             readonly=True, required=True)
    sale_move_id = fields.Many2one('stock.move', 'Sale Move', required=False,
                                   readonly=True, ondelete='cascade', index=1)
    sale_picking_id = fields.Many2one(related='sale_move_id.picking_id',
                                      string='Sale picking',
                                      readonly=True)
    return_picking_id = fields.Many2one('stock.picking', 'Return Picking',
                                        required=False, readonly=True,
                                        ondelete='cascade', index=1)
    loss_move_id = fields.Many2one('stock.move', 'Loss Move', required=False,
                                   readonly=True, ondelete='cascade', index=1)
    loss_picking_id = fields.Many2one(related='loss_move_id.picking_id',
                                      string='Loss picking',
                                      readonly=True)
    user_id = fields.Many2one('res.users', 'Comercial', required=False,
                              readonly=False, ondelete='cascade', index=1)
    # cost_subtotal = fields.Float('Cost', related='move_id.cost_subtotal',
    #                              store=True, readonly=True) TODO:Migrar.

    @api.multi
    def sale(self):
        move_obj = self.env['stock.move']
        picking_type_id = self.env.ref('stock.picking_type_out')
        for deposit in self:
            picking = self.env['stock.picking'].create(
                {'picking_type_id': picking_type_id.id,
                 'partner_id': deposit.partner_id.id,
                 'origin': deposit.sale_id.name,
                 'date_done': datetime.now(),
                 'commercial': deposit.user_id.id,
                 'group_id': deposit.move_id.group_id.id,
                 'location_id': deposit.move_id.location_dest_id.id,
                 'location_dest_id': picking_type_id.default_location_dest_id.id})
            values = {
                'product_id': deposit.product_id.id,
                'product_uom_qty': deposit.product_uom_qty,
                'product_uom': deposit.product_uom.id,
                'partner_id': deposit.partner_id.id,
                'name': 'Sale Deposit: ' + deposit.move_id.name,
                'location_id': deposit.move_id.location_dest_id.id,
                'location_dest_id': deposit.partner_id.property_stock_customer.id,
                'picking_id': picking.id,
                'commercial': deposit.user_id.id,
                'group_id': deposit.move_id.group_id.id
            }
            move = move_obj.create(values)
            move._action_confirm()
            picking.action_assign()
            picking.action_done()
            deposit.move_id.sale_line_id.write({'qty_invoiced': deposit.move_id.sale_line_id.qty_invoiced-deposit.product_uom_qty, 'invoice_status': 'to invoice'})
            deposit.write({'state': 'sale', 'sale_move_id': move.id})

    @api.one
    def _prepare_deposit_move(self, picking, group):
        move_template = {
            'name': 'RET' or '',
            'product_id': self.product_id.id,
            'product_uom': self.product_uom.id,
            'product_uom_qty': self.product_uom_qty,
            'product_uos': self.product_uom.id,
            'location_id': self.move_id.location_dest_id.id,
            'location_dest_id':
                picking.picking_type_id.default_location_dest_id.id,
            'picking_id': picking.id,
            'partner_id': self.partner_id.id,
            'move_dest_id': False,
            'state': 'draft',
            'company_id': self.company_id.id,
            'group_id': group.id,
            'procurement_id': False,
            'origin': False,
            'route_ids':
                picking.picking_type_id.warehouse_id and
                [(6, 0,
                  [x.id for x in
                   picking.picking_type_id.warehouse_id.route_ids])] or [],
            'warehouse_id': picking.picking_type_id.warehouse_id.id,
            'invoice_state': 'none'
        }
        return move_template

    @api.multi
    def _create_stock_moves(self, picking=False):
        self.ensure_one()
        stock_move = self.env['stock.move']
        todo_moves = self.env['stock.move']
        new_group = self.env['procurement.group'].create(
            {'name': 'deposit RET', 'partner_id': self.partner_id.id})
        for vals in self._prepare_deposit_move(picking, new_group):
            todo_moves += stock_move.create(vals)

        todo_moves._action_confirm()
        todo_moves._force_assign()

    @api.multi
    def return_deposit(self):
        picking_type_id = self.env.ref('stock.picking_type_in')
        for deposit in self:
            picking = self.env['stock.picking'].create(
                {'picking_type_id': picking_type_id.id,
                 'partner_id': deposit.partner_id.id,
                 'location_id': deposit.move_id.location_dest_id.id,
                 'location_dest_id': picking_type_id.default_location_dest_id.id})
            deposit._create_stock_moves(picking)
            deposit.write({'state': 'returned',
                           'return_picking_id': picking.id})

    @api.model
    def send_advise_email(self):
        deposits = self.search([('return_date', '=', fields.Date.today())])
        #~ mail_pool = self.env['mail.mail']
        #~ mail_ids = self.env['mail.mail']
        template = self.env.ref('stock_deposit.stock_deposit_advise_partner', False)
        for deposit in deposits:
            ctx = dict(self._context)
            ctx.update({
                'default_model': 'stock.deposit',
                'default_res_id': deposit.id,
                'default_use_template': bool(template.id),
                'default_template_id': template.id,
                'default_composition_mode': 'comment',
                'mark_so_as_sent': True
            })
            composer_id = self.env['mail.compose.message'].with_context(
                ctx).create({})
            composer_id.with_context(ctx).send_mail()
            #~ mail_id = template.send_mail(deposit.id)
            #~ mail_ids += mail_pool.browse(mail_id)
        #~ if mail_ids:
            #~ mail_ids.send()
        return True

    @api.multi
    def deposit_loss(self):
        move_obj = self.env['stock.move']
        picking_type_id = self.env.ref('stock.picking_type_out')
        deposit_loss_loc = self.env.ref('stock_deposit.stock_location_deposit_loss')
        for deposit in self:
            group_id = deposit.sale_id.procurement_group_id
            picking = self.env['stock.picking'].create(
                {'picking_type_id': picking_type_id.id,
                 'partner_id': deposit.partner_id.id,
                 'origin': deposit.sale_id.name,
                 'date_done': fields.Datetime.now(),
                 'invoice_state': 'none',
                 'commercial': deposit.user_id.id,
                 'location_id': deposit.move_id.location_dest_id.id,
                 'location_dest_id': deposit_loss_loc.id,
                 'group_id': group_id.id,
                 'not_sync': True})
            values = {
                'product_id': deposit.product_id.id,
                'product_uom_qty': deposit.product_uom_qty,
                'product_uom': deposit.product_uom.id,
                'partner_id': deposit.partner_id.id,
                'name': u'Loss Deposit: ' + deposit.move_id.name,
                'location_id': deposit.move_id.location_dest_id.id,
                'location_dest_id': deposit_loss_loc.id,
                'invoice_state': 'none',
                'picking_id': picking.id,
                'commercial': deposit.user_id.id,
                'group_id': group_id.id
            }
            move = move_obj.create(values)
            move._action_confirm()
            picking.action_assign()
            picking.action_done()
            deposit.write({'state': 'loss', 'loss_move_id': move.id})

    @api.multi
    def create_invoice(self,journal_id=None):
        deposit_obj = self.env['stock.deposit']
        deposits = self.filtered(lambda d:d.state=='sale')
        invoice_ids = []
        if not deposits:
            raise exceptions.Warning(_('No deposit selected'))
        sales = list(set([x.sale_id for x in deposits]))
        for sale in sales:
            sale_deposit = deposit_obj.search(
                [('id', 'in', deposits.ids), ('sale_id', '=', sale.id)])

            sale_lines = sale_deposit.mapped('move_id.sale_line_id')
            my_context = dict(self.env.context)
            my_context['invoice_deposit'] = True
            inv_vals = sale._prepare_invoice()
            if self.env.context.get('force_partner_id',False):
                partner_id = self.env.context.get('force_partner_id')
                inv_vals['partner_id'] = partner_id.id
                inv_vals['partner_shipping_id'] = partner_id.id
                inv_vals['payment_term_id'] = \
                    partner_id.property_payment_term_id.id
            else:
                partner_id = sale.partner_id
            inv_vals['journal_id'] = journal_id.id if journal_id else partner_id.commercial_partner_id.invoice_type_id.journal_id.id
            if not inv_vals.get("payment_term_id", False):
                inv_vals['payment_term_id'] = \
                    partner_id.property_payment_term_id.id
            if not inv_vals.get("payment_mode_id", False):
                inv_vals['payment_mode_id'] = \
                    partner_id.customer_payment_mode_id.id
            if not inv_vals.get("partner_bank_id", False):
                inv_vals['partner_bank_id'] = partner_id.bank_ids \
                    and partner_id.bank_ids[0].id or False
            invoice = self.env['account.invoice'].create(inv_vals)
            for line in sale_lines:
                deposit = self.filtered(lambda d: d.move_id.sale_line_id.id==line.id)
                invoice_line = line.with_context(my_context).invoice_line_create(invoice.id, sum(deposit.mapped('product_uom_qty')))
                invoice_line.move_line_ids = [(4, deposit.sale_move_id.id)]
                line.qty_invoiced=line.product_qty
            invoice_ids.append(invoice.id)
            sale_deposit.write({'invoice_id': invoice.id})
        deposits.write({'state': 'invoiced'})
        return invoice_ids


    @api.multi
    def revert_sale(self):
        move_obj = self.env['stock.move']
        picking_type_id = self.env.ref('stock.picking_type_in')
        for deposit in self:
            picking = self.env['stock.picking'].create(
                {'picking_type_id': picking_type_id.id,
                 'partner_id': deposit.partner_id.id,
                 'origin': deposit.sale_picking_id.name,
                 'date_done': datetime.now(),
                 'commercial': deposit.user_id.id,
                 'group_id': deposit.sale_move_id.group_id.id,
                 'location_id': deposit.sale_move_id.location_dest_id.id,
                 'location_dest_id': deposit.sale_move_id.location_id.id})
            values = {
                'product_id': deposit.product_id.id,
                'product_uom_qty': deposit.product_uom_qty,
                'product_uom': deposit.product_uom.id,
                'partner_id': deposit.partner_id.id,
                'name': 'Return Sale Deposit: ' + deposit.sale_move_id.name,
                'location_id': deposit.sale_move_id.location_dest_id.id,
                'location_dest_id': deposit.sale_move_id.location_id.id,
                'picking_id': picking.id,
                'commercial': deposit.user_id.id,
                'group_id': deposit.sale_move_id.group_id.id
            }
            move = move_obj.create(values)
            move._action_confirm()
            picking.action_assign()
            picking.action_done()
            new_qty_invoiced = deposit.move_id.sale_line_id.qty_invoiced + deposit.product_uom_qty
            if new_qty_invoiced == deposit.move_id.sale_line_id.product_qty:
                invoice_status = 'invoiced'
            else:
                invoice_status = 'to invoice'
            deposit.move_id.sale_line_id.write({'qty_invoiced': new_qty_invoiced , 'invoice_status': invoice_status})
            deposit.write({'state': 'draft', 'sale_move_id': False})

    @api.multi
    def revert_invoice(self):
        for deposit in self:
            if deposit.invoice_id:
                if deposit.invoice_id.state not in ['draft','cancel']:
                    raise UserError(_("This deposit has invoices in non-draft status, please check it before reverting it"))
                deposit.invoice_id.action_invoice_cancel()
                deposit.invoice_id = False
                deposit.revert_sale()

