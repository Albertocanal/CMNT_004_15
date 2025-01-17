##############################################################################
#
#    Copyright (C) 2014 Pexego Sistemas Informáticos All Rights Reserved
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

from odoo import models, fields, api


class SaleOrder(models.Model):

    _inherit = 'sale.order'
    transporter_id = fields.Many2one('transportation.transporter',
                                     'transporter')
    service_id = fields.Many2one('transportation.service',
                                 'Transport service')
    delivery_type = fields.Selection([
        ('shipping', 'Shipping'),
        ('carrier', 'Carrier - Customer'),
        ('installations', 'Pickup in installations')],
        'Delivery type', required=True, default='shipping')

    @api.multi
    @api.onchange('partner_id')
    def onchange_partner_id(self):
        super().onchange_partner_id()
        if self.partner_id:
            self.transporter_id = self.partner_id.transporter_id.id
            self.service_id = self.partner_id.service_id.id
            self.delivery_type = self.partner_id.delivery_type

    @api.multi
    @api.onchange('partner_shipping_id')
    def onchange_partner_id_transporter(self):
        transporter_ids = self.env['transportation.transporter'].search(
            [('country_group_id.country_ids', 'in', [self.partner_shipping_id.country_id.id])])
        if transporter_ids:
            if self.transporter_id not in transporter_ids:
                self.transporter_id = False
            return {'domain': {'transporter_id': [('id', 'in', transporter_ids.mapped("id"))]}}
        all_transporters_ids = self.env['transportation.transporter'].search([])
        return {'domain': {'transporter_id': [('id', 'in', all_transporters_ids.mapped("id"))]}}



    @api.multi
    @api.onchange('transporter_id')
    def onchange_transporter_id(self):
        service_ids = [x.id for x in self.transporter_id.service_ids]
        if service_ids:
            if self.service_id.id not in service_ids:
                self.service_id = False
            return {'domain': {'service_id': [('id', 'in', service_ids)]}}
        all_services = [x.id for x in self.env['transportation.service'].search([])]
        return {'domain': {'service_id': [('id', 'in', all_services)]}}

