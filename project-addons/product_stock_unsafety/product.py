# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2016 Comunitea servicios Tecnológicos
#    $Omar Castiñeira Saavedra$ <omar@comunitea.com>
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
from openerp import models, fields, api
from datetime import date
from dateutil.relativedelta import relativedelta


class product_product(models.Model):
    _inherit = 'product.product'

    @api.model
    def get_daily_sales(self):
        stock_per_day = 0
        virtual_stock = self.virtual_available
        replacements = self.search([('replacement_id', '=', self.id)])
        if replacements:
            virtual_stock += replacements[0].virtual_available
        if virtual_stock:
            last_sixty_days_sales = self.last_sixty_days_sales
            if replacements:
                last_sixty_days_sales += replacements[0].last_sixty_days_sales
            stock_per_day = last_sixty_days_sales / 60.0
        return stock_per_day

    @api.one
    @api.depends("last_sixty_days_sales")
    def _calc_remaining_days(self):
        stock_days = 0.00
        stock_per_day = self.get_daily_sales()
        virtual_available = self.virtual_available
        if stock_per_day > 0 and virtual_available:
            stock_days = round(virtual_available / stock_per_day)

        self.remaining_days_sale = stock_days

    remaining_days_sale = fields.Float('Remaining Stock Days', readonly=True,
                                       compute='_calc_remaining_days',
                                       help="Stock measure in days of sale "
                                       "computed consulting sales in sixty "
                                       "days with stock.", store=True)
    replacement_id = fields.Many2one("product.product", "Replaced by")