from odoo import models, fields, api
from odoo import tools


class SaleReport(models.Model):
    _inherit = 'sale.report'

    benefit = fields.Float('Benefit', readonly=True)
    cost_price = fields.Float('Cost Price', readonly=True)

    def _select(self):
        select_str = super(SaleReport, self)._select()
        this_str = \
            """,sum(l.price_subtotal)  - sum(l.purchase_price*l.product_uom_qty)
            as benefit, sum(l.purchase_price*l.product_uom_qty)
            as cost_price"""
        return select_str + this_str

    def _where(self):
        where_str = "l.deposit = false"
        return where_str

    @api.model_cr
    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute("""CREATE or REPLACE VIEW %s as (
            %s
            FROM ( %s )
            WHERE %s
            %s
            )""" % (self._table, self._select(), self._from(), self._where(),
                    self._group_by()))
