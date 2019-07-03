# © 2019 Comunitea
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
{
    'name': 'Stock customization to print',
    'version': '1.0',
    'category': 'Customization',
    'description': """This module adds associated products""",
    'author': 'Comunitea',
    'website': '',
    'depends': ['base', 'stock_picking_report_valued', 'base_report_to_printer',
                'custom_account', 'picking_incidences',
                'reserve_without_save_sale', 'sale_display_stock',
                'stock_reserve_sale', 'product_brand', 'sale_customer_discount',
                'product_stock_unsafety', 'stock', 'stock_landed_costs'],
    'data': ['views/ir_attachment_view.xml',
             'security/stock_custom_security.xml',
             'stock_custom_report.xml',
             'report/stock_report.xml',
             'views/stock_view.xml',
             'views/partner_view.xml',
             'views/product_view.xml',
             'views/sale_view.xml',
             'security/ir.model.access.csv'],
    'installable': True
}
