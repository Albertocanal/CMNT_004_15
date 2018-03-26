# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2015 Pexego All Rights Reserved
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
from openerp import models, fields, api, exceptions, SUPERUSER_ID


class AccountInvoiceLine(models.Model):

    _inherit = 'account.invoice.line'

    cost_unit = fields.Float("Product cost price")


class AccountInvoice(models.Model):

    _inherit = 'account.invoice'

    @api.multi
    def invoice_validate(self):
        res = super(AccountInvoice, self).invoice_validate()
        for inv in self:
            for line in inv.invoice_line:
                line.write({'cost_unit': line.product_id.standard_price})
        return res
