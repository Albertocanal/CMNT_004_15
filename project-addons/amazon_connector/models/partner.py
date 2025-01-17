from odoo import models, fields, api, exceptions, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    amazon_child_ids = fields.One2many('res.partner', 'amazon_parent_id', string='Amazon Contacts')
    amazon_parent_id = fields.Many2one('res.partner')


    @api.depends('amazon_parent_id.name')
    def _compute_display_name(self):
        super(ResPartner, self)._compute_display_name()
        for partner in self:
            if partner.amazon_parent_id:
                partner.display_name = "%s, %s" % (partner.amazon_parent_id.name, partner.display_name)

