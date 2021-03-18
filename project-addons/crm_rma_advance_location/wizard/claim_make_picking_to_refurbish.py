from odoo import fields, models, api, exceptions, _
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
import time


class ClaimMakePickingToRefurbishWizard(models.TransientModel):
    _name = "claim.make.picking.to.refurbish.wizard"

    @api.model
    def _get_picking_lines(self):
        wiz_lines = []
        for move in self.env['stock.picking'].browse(self.env.context['active_id']).move_lines:
            new_line = {'product_id': move.product_id.id,
                        'move_id': move.id,
                        'product_qty': move.product_uom_qty}
            product = move.product_id
            domain = [('claim_type', '=',
                       self.env.ref('crm_claim_type.crm_claim_type_supplier').id),
                      ('stage_id', '=', self.env.ref('crm_claim.stage_claim5').id)]
            if product.product_brand_id.code in ['Ajax', 'HIKVISION']:
                domain += [('partner_id', 'in', product.seller_ids.ids)]
            else:
                domain += [('partner_id', '=', product.last_supplier_id.id)]
            claim_id = self.env['crm.claim'].search(domain)
            if claim_id and len(claim_id)==1:
                new_line.update({'claim_id':claim_id.id})
            wiz_lines.append(new_line)
        return wiz_lines

    @api.model
    def _get_source_loc(self):
        warehouse_id = self._get_default_warehouse()
        return warehouse_id.lot_rma_id.id

    @api.model
    def _get_dest_loc(self):
        return self.env.ref('location_moves.stock_location_damaged').id

    picking_line_source_location = fields.Many2one('stock.location',
                                                   'Source Location',
                                                   help="Location where the returned products are from.",
                                                   required=True, default=_get_source_loc)
    picking_line_dest_location = fields.Many2one('stock.location',
                                                 'Dest. Location',
                                                 help="Location where the system will stock the returned products.",
                                                 required=True, default=_get_dest_loc)
    picking_line_ids = fields.One2many('claim.make.picking.to.refurbish.line',
                                       'wizard_id',
                                       'Picking lines', default=_get_picking_lines)

    @api.model
    def _get_default_warehouse(self):
        warehouse_id = self.env['crm.claim']._get_default_warehouse()
        return warehouse_id

    @api.multi
    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    @api.multi
    def action_create_picking(self):
        picking_obj = self.env['stock.picking']
        type_ids = self.env['stock.picking.type'].search([('code', '=', 'outgoing')])
        note = 'Internal picking from RMA to refurbish'
        prev_picking = picking_obj.browse(self.env.context['active_id'])
        partner_id = prev_picking.partner_id.id
        default_picking_data = {
            'move_lines': [],
            'location_id': self.picking_line_source_location.id,
            'location_dest_id': self.picking_line_dest_location.id,
            'picking_type_id': type_ids and type_ids[0].id,
            'note': note,
            'claim_id': prev_picking.claim_id.id,
            'partner_id': partner_id
        }
        picking_id = prev_picking.copy(default_picking_data)
        for wizard_picking_line in self.picking_line_ids:
            default_move_data = {
                'date': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
                'date_expected': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
                'partner_id': partner_id,
                'picking_id': picking_id.id,
                'company_id': prev_picking.company_id.id,
                'location_id': self.picking_line_source_location.id,
                'location_dest_id': self.picking_line_dest_location.id,
                'note': note,
                'picking_type_id': type_ids and type_ids[0].id,
            }
            wizard_picking_line.move_id.copy(default_move_data)
        if picking_id:
            picking_id.action_assign()
            picking_id.action_done()
        damaged_products = []
        rmps = self.env['crm.claim']
        for l in self.picking_line_ids:
            product = l.move_id.product_id
            qty = l.move_id.product_uom_qty
            if l.claim_id:
                rmp_id = self.env['crm.claim'].browse(l.claim_id.id)
            else:
                domain = [('claim_type', '=',
                           self.env.ref('crm_claim_type.crm_claim_type_supplier').id),
                          ('stage_id', '=', self.env.ref('crm_claim.stage_claim5').id)]
                if product.product_brand_id.code in ['Ajax', 'HIKVISION']:
                    domain += [('partner_id', 'in', product.seller_ids.ids)]
                else:
                    domain += [('partner_id', '=', product.last_supplier_id.id)]
                rmp_id = self.env['crm.claim'].search(domain)
                if not rmp_id:
                    raise exceptions.UserError(
                        _("There is no RMP in progress for this supplier (%s)") %
                        l.move_id.product_id.last_supplier_id.name)
                elif len(rmp_id)>1:
                    raise exceptions.UserError(
                        _("There are %i RMP in progress for this supplier (%s). (%s)") % (
                            len(rmp_id), l.move_id.product_id.last_supplier_id.name, rmp_id.mapped('number')))
            claim_line = self.env['claim.line'].create({
                'product_id': product.id,
                'name': l.problem_description,
                'claim_origine': 'broken_down',
                'product_returned_qty': qty,
                'claim_id': rmp_id.id,
                'prodlot_id': l.prodlot_id
            })
            damaged_products.append((qty, {"product_id": product.id,
                                           "prodlot_id": l.prodlot_id,
                                           "problem_description": l.problem_description,
                                           "user_id": self.env.user.id,
                                           "supplier_id": product.last_supplier_id.id,
                                           "claim_id": rmp_id.id,
                                           "claim_line_id": claim_line.id,
                                           "printed": False}))
            rmps += rmp_id
        for product in damaged_products:
            for i in range(int(product[0])):
                self.env['damaged.product'].create(product[1])

        action = self.env.ref('stock.action_picking_tree_all')
        result = action.read()[0]
        result['context'] = {}
        res = self.env.ref('stock.view_picking_form', False)
        result['views'] = [(res and res.id or False, 'form')]
        result['res_id'] = picking_id.id
        message = _("Products successfully entered in the following RMPs %s") % rmps.mapped('number')
        picking_id.env.user.notify_info(message=message, sticky=True)
        return result

    select_claim = fields.Boolean()


class ClaimMakePickingToRefurbishLine(models.TransientModel):
    _name = "claim.make.picking.to.refurbish.line"

    move_id = fields.Many2one('stock.move')
    prodlot_id = fields.Char("Product Lot / Serial")
    problem_description = fields.Char()
    wizard_id = fields.Many2one('claim.make.picking.to.refurbish.wizard')
    product_id = fields.Many2one('product.product')
    product_qty = fields.Float()
    claim_id = fields.Many2one("crm.claim",domain=lambda self: [('claim_type', '=',
                           self.env.ref('crm_claim_type.crm_claim_type_supplier').id),
                          ('stage_id', '=', self.env.ref('crm_claim.stage_claim5').id)])
