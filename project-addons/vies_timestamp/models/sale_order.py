##############################################################################
#
#    Copyright (C) 2015 Comunitea All Rights Reserved
#    @author Alberto Luengo Cabanillas
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

from odoo import fields, models, _, tools, api, exceptions, tools
import time
from urllib.request import getproxies
import base64


class SaleOrder(models.Model):

    _inherit = 'sale.order'

    vies_validation_check = fields.Boolean('VAT Validated through VIES?',
                                           copy=False)
    vies_validation_timestamp = fields.\
        Datetime('Date when VAT validated through VIES', copy=False)
    waiting_vies_validation = fields.Boolean('Waiting for vies validation',
                                             copy=False, readonly=True)
    force_vies_validation = fields.Boolean('Vies validation forced',
                                           copy=False, readonly=True)
    fiscal_position = fields.Many2one('account.fiscal.position',
                                      'Fiscal Position', readonly=True,
                                      states={'draft': [('readonly', False)],
                                              'sent': [('readonly', False)],
                                              'reserve': [('readonly',
                                                           False)]})

    @api.multi
    def check_vat_ext(self):
        date_now = time.strftime('%Y-%m-%d %H:%M:%S')
        result = True
        sale = self[0]
        partner_vat = sale.partner_id.vat
        url = "http://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"

        if sale.force_vies_validation:
            result = True
            vals = {'vies_validation_check': result,
                    'vies_validation_timestamp': date_now,
                    'waiting_vies_validation': not result}
            sale.write(vals)
            return result

        if partner_vat and not sale.force_vies_validation and \
                sale.fiscal_position_id and \
                sale.fiscal_position_id.require_vies_validation:
            vat = partner_vat.replace(" ", "")
            try:
                from suds.client import Client
            except:
                raise exceptions.\
                    Warning(_('import module "suds" failed - check VIES '
                              'needs this module'))

            country_code = '%s' % (vat[:2])
            vat_number = '%s' % (vat[2:])
            res = {}
            try:
                client = Client(url, proxy=getproxies())
                res = client.service.\
                    checkVat(countryCode=country_code, vatNumber=vat_number)
                result = bool(res["valid"])
            except:
                result = None

            if result is not None:
                from reportlab.pdfgen import canvas
                route = tools.config["data_dir"] + '/filestore/'
                name = '%s_VIES.pdf' % sale.\
                    name.replace(" ", "").replace("\\", "").replace("/", "").\
                    replace("-", "_")
                route += name
                c = canvas.Canvas(route)
                height = 700
                c.drawString(100, height, url)
                height = height - 25
                for key in dict(res):
                    c.drawString(100, height,
                                 key + u": " + tools.ustr(res[key]).
                                 replace('\n', ' '))
                    height = height - 25
                c.showPage()
                c.save()
                with open(route, "rb") as file:
                    a = base64.b64encode(file.read())
                attach_vals = {
                    'name': name,
                    'datas_fname': name,
                    'datas': a,
                    'res_id': sale.id,
                    'res_model': 'sale.order',
                }
                self.env['ir.attachment'].create(attach_vals)
            else:
                result = False

            vals = {'vies_validation_check': result,
                    'vies_validation_timestamp': date_now,
                    'waiting_vies_validation': not result}
            sale.write(vals)
            if not result:
                raise exceptions. \
                    Warning(_('The partner is not registered in VIES so the order cannot be processed under the intra-community regime'))

        return result

    @api.multi
    def action_force_vies_validation(self):
        self.write({'force_vies_validation': True,
                    'waiting_vies_validation': False})
        for order in self:
            followers = order.message_follower_ids
            order.message_post(body=_("The user %s forced vies validation.") %
                               self.env.user.name,
                               subtype='mt_comment',
                               partner_ids=followers)
        return True

    @api.multi
    def action_confirm(self):
        self.check_vat_ext()
        return super(SaleOrder, self).action_confirm()

    @api.multi
    def action_cancel(self):
        res = super(SaleOrder, self).action_cancel()
        for order in self:
            order.waiting_vies_validation = False
        return res

    # @api.multi
    # def copy(self, default=None):
    #     self.ensure_one()
    #     res = super(SaleOrder, self).copy(default)
    #     res.force_vies_validation = False
    #     return res