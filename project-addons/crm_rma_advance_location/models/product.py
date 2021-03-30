from odoo import fields, models


class ProductTemplate(models.Model):

    _inherit = 'product.template'

    rmp_partner = fields.Many2one('res.partner')

