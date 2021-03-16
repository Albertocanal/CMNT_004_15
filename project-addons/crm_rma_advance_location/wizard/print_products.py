from odoo import fields, models, api, exceptions, _


class PrintDamagedProductWizard(models.TransientModel):
    _name = "print.damaged.product.wizard"

    @api.model
    def _get_products(self):
        return self.env['damaged.product'].browse(self.env.context['active_ids'])

    damaged_products = fields.Many2many('damaged.product',
                                        'print_damaged_product_id',
                                        'damaged_product', default=_get_products)

    def print(self):
        self.damaged_products.write({"printed": True})
        return self.env.ref('crm_rma_advance_location.report_damaged_products').report_action(self.damaged_products.ids,
                                                                                              config=False)
