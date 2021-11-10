from odoo import models, fields, api, exceptions, _
from odoo.exceptions import ValidationError

class StockInvoiceDeposit(models.TransientModel):
    _name = 'damaged.deposit'

    @api.multi
    def _get_active_deposits(self):
        wiz_lines = []
        deposit_obj = self.env['stock.deposit']
        deposit_ids = self.env.context.get('active_ids', [])
        deposits = deposit_obj.search([('id', 'in', deposit_ids),
                                       ('state', '=', 'draft')])
        for deposit in deposits:
            wiz_lines.append({'deposit_id': deposit.id,
                              'partner_id': deposit.partner_id.id,
                              'sale_id': deposit.sale_id.id,
                              'picking_id': deposit.picking_id.id,
                              'date': deposit.delivery_date,
                              'product_id': deposit.product_id.id,
                              'qty_damaged': deposit.product_uom_qty})
        return wiz_lines

    deposit_change_qty = fields.One2many('damaged.deposit.change.qty', 'wizard_id',
                                         string='Deposits', default=_get_active_deposits)

    @api.multi
    def send_damaged_deposits(self):
        deposit_ids = []
        # Change deposit quantity -> create a new deposit with the remaining qty
        for line in self.deposit_change_qty:
            qty_deposit = line.deposit_id.product_uom_qty
            if line.qty_damaged> qty_deposit or line.qty_damaged == 0:
                raise ValidationError(_('The quantity to send to damaged location cannot be zero or greater than the original.'))
            elif line.qty_damaged < qty_deposit:
                new_deposit = line.deposit_id.copy()
                new_deposit.write({'product_uom_qty': qty_deposit - line.qty_damaged})
                line.deposit_id.write({'product_uom_qty': line.qty_damaged})
            deposit_ids.append(line.deposit_id.id)
        deposits = self.env['stock.deposit'].browse(deposit_ids)
        deposits.send_to_damaged()
            


class DamagedDepositChangeQty(models.TransientModel):
    _name = 'damaged.deposit.change.qty'

    wizard_id = fields.Many2one('damaged.deposit')
    deposit_id = fields.Many2one('stock.deposit', "Deposit", readonly=True)
    partner_id = fields.Many2one('res.partner', "Partner", readonly=True)
    sale_id = fields.Many2one('sale.order', "Order", readonly=True)
    picking_id = fields.Many2one('stock.picking', "Picking", readonly=True)
    date = fields.Datetime(string='Date', readonly=True)
    product_id = fields.Many2one('product.product', "Product", readonly=True)
    qty_damaged = fields.Float("Qty Damaged")
