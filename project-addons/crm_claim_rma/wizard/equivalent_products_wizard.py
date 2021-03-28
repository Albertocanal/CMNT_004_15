from odoo import fields, models, api, _, exceptions


class EquivalentProductsWizard(models.TransientModel):

    _name = 'equivalent.products.wizard'
    _description = 'Wizard for change products in claim.'

    product_tag_ids = fields.Many2many("product.tag", "product_tag_wzf_equivalent_rel", "wizard_id", "tag_id", "Tags")
    product_id = fields.Many2one('product.product', 'Product selected')
    line_id = fields.Many2one('claim.line', 'Line')
    real_stock = fields.Float("Real Stock", readonly=True)
    virtual_stock = fields.Float("Virtual Stock", readonly=True)

    def default_get(self, fields):
        res = super(EquivalentProductsWizard, self).default_get(fields)
        if self.env.context.get('claim_line'):
            claim_line_id = self.env.get('claim.line').browse(self.env.context['claim_line'])
            res['product_id'] = claim_line_id.product_id.id
            res['real_stock'] = claim_line_id.product_id.qty_available
            res['virtual_stock'] = claim_line_id.product_id.virtual_available
            res['product_tag_ids'] = [(6, 0, claim_line_id.product_id.tag_ids.ids)]
        return res

    @api.multi
    def select_product(self):
        self.line_id.equivalent_product_id = self.product_id

    @api.multi
    def delete_product(self):
        if self.line_id.move_out_customer_state and self.line_id.move_out_customer_state != 'cancel':
            raise exceptions.UserError(_("There are open pickings that contain this product"))
        else:
            self.line_id.equivalent_product_id = None
            self.env.user.notify_info(title=_("Product deleted"), message=_("Check the status of the line"))

