# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2014 Pexego All Rights Reserved
#    $Jesús Ventosinos Mayor <jesus@pexego.es>$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
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

from openerp import models, fields, api, exceptions, _


class MrpCustomizationWizard(models.TransientModel):

    _name = "mrp.customization.wizard"

    product_id = fields.Many2one('product.product', 'Product', required=True,
                                 domain=[('type', '=', 'product'),
                                         ('custom', '=', False)])
    qty = fields.Float('Quantity', required=True)
    customization_type_ids = fields.Many2many('mrp.customize.type',
                                              'customization_wzd_ctype_rel',
                                              'wzd_id', 'ctype_id',
                                              'Customization types',
                                              required=True)
    product_uom = fields.Many2one('product.uom', 'UoM', readonly=True)
    name = fields.Char("Production name", required=True)
    can_mount_id = fields.Many2one('product.product.mount', 'Mount')
    requires_mount = fields.Boolean('Requires mount')
    requires_partner = fields.Boolean('Requires partner')
    partner_id = fields.Many2one('res.partner', 'Related partner',
                                 domain=[('customer', '=', True)])

    @api.one
    @api.onchange('customization_type_ids')
    def onchange_customization_types(self):
        requires_mount = False
        requires_partner = False
        for custom in self.customization_type_ids:
            if custom.aux_product:
                requires_mount = True
            else:
                requires_partner = True
        self.requires_mount = requires_mount
        self.requires_partner = requires_partner

    @api.one
    @api.onchange('product_id')
    def on_change_product_id(self):
        if self.product_id:
            self.product_uom = self.product_id.uom_id.id
        else:
            self.product_uom = False

    @api.one
    def create_customization(self):
        require_mount = False
        require_partner = False
        prod_obj = self.env["product.product"]
        for custom in self.customization_type_ids:
            if custom.aux_product:
                require_mount = True
            else:
                require_partner = True

        if not self.product_id.default_code:
            raise exceptions.Warning(
                _('This product not have default code'))
        product_code = self.product_id.default_code
        if require_mount:
            if not self.can_mount_id.product_id.default_code:
                raise exceptions.Warning(
                    _('The product to mount not have default code'))
            product_code += '#' + self.can_mount_id.product_id.\
                default_code
        if require_partner:
            if not self.partner_id.ref:
                raise exceptions.Warning(
                    _('The partner %s not have reference') %
                    self.partner_id.name)
            product_code += '|' + str(self.partner_id.ref)

        for custom in self.customization_type_ids:
            if not custom.aux_product:
                product_code += '|' + str(custom.code)

        product = prod_obj.get_product_customized(product_code,
                                                  self.can_mount_id)
        if self.customization_type_ids:
            type_ids = [(6, 0, [x.id for x in self.customization_type_ids])]
        else:
            type_ids = False
        for x in range(int(self.qty)):
            mrp_args = {
                'type_ids': type_ids,
                'product_id': product.id,
                'bom_id': product.bom_ids[0].id,
                'product_uom': product.uom_id.id,
                'product_qty': 1,
                'production_name': self.name
            }
            production = self.env['mrp.production'].create(mrp_args)
            production.signal_workflow('button_confirm')

        return True
