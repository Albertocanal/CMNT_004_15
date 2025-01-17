##############################################################################
#
#    Authors: Santiago Argüeso
#    Copyright Pexego SL 2012
#    Omar Castiñeira Saavedra Copyright Comunitea SL 2015
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
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

{
    'name': 'Pending invoices accounting from  Picking',
    'description': "Allow to account invoices when transfering incoming "
                   "pickings, when invoice is validated previous account move "
                   "is reverted.",
    'version': '11.0.0.0.1',
    'author': 'Pexego',
    'category': 'Finance',
    'website': 'http://www.pexego.es',
    'depends': ['base',
                'account',
                'account_reversal',
                'stock',
                'purchase_discount',
                'custom_account',
                'purchase_stock_picking_invoice_link',
                'stock_picking_back2draft'],
    'data': ['views/res_company_view.xml',
             'views/stock_picking_view.xml',
             'data/email_template.xml',
             'data/cron.xml'],
    'active': False,
    'installable': True,
}
