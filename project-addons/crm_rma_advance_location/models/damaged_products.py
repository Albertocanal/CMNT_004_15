from odoo import models, api, fields


class DamagedProduct(models.Model):

    _name = "damaged.product"

    product_id = fields.Many2one("product.product")
    prodlot_id = fields.Char("Product Lot / Serial")
    problem_description = fields.Char()
    user_id = fields.Many2one("res.users")
    supplier_id = fields.Many2one("res.partner")
    claim_id = fields.Many2one("crm.claim")
    claim_line_id = fields.Many2one("claim.line")
    printed = fields.Boolean()
