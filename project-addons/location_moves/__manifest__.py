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

{
    'name': "Stock location moves",
    'version': '11.0',
    'category': 'stock',
    'description': """""",
    'author': 'Pexego',
    'website': 'www.pexego.es',
    "depends": ['stock', 'purchase_picking'],
    "data": ['data/cron.xml','data/stock_data.xml', 'data/parameters.xml', 'wizard/location_moves_view.xml',
             "views/stock_view.xml"],
    "installable": True
}
