# © 2019 Comunitea
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import models, fields, tools
import odoo.addons.decimal_precision as dp


class AccountInvoiceCyCOld(models.Model):

    _name = 'account.invoice.cyc.old'
    _auto = False

    MONTHS = [(1, 'January'), (2, 'February'), (3, 'March'),
              (4, 'April'), (5, 'May'), (6, 'June'), (7, 'July'),
              (8, 'August'), (9, 'September'), (10, 'October'),
              (11, 'November'), (12, 'December')]

    country_id = fields.Many2one('res.country', 'Country', readonly=True)
    credit_covered = fields.Float('Credit covered', readonly=True,
                                  digits=dp.get_precision('Account'))
    credit_not_covered = fields.Float(
        'Credit not covered', readonly=True,
        digits=dp.get_precision('Account'))
    not_credit = fields.Float('No credit', readonly=True,
                              digits=dp.get_precision('Account'))
    cash = fields.Float('Cash', readonly=True,
                        digits=dp.get_precision('Account'))
    invoice_year = fields.Char('Year', readonly=True)
    invoice_month = fields.Selection(MONTHS, string="Month", readonly=True)
    amount_total = fields.Float('Total', readonly=True,
                                digits=dp.get_precision('Account'))
    invoice_state = fields.Selection([('open', 'Open'),('paid', 'Paid')],
                                     string="Invoice state", readonly=True)
    user_id = fields.Many2one("res.users", "Comercial", readonly=True)
    area_id = fields.Many2one('res.partner.area', 'Area', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self._cr, self._table)
        self._cr.execute("""CREATE VIEW account_invoice_cyc_old as (
select min(a.id) as id, a.country_id, sum(a.credit_covered) as credit_covered,
sum(a.credit_not_covered) as credit_not_covered, a.user_id, a.area_id,
sum(a.not_credit) as not_credit, sum(a.cash) as cash, a.invoice_year,
a.invoice_month, a.state as invoice_state, sum(a.credit_covered) +
sum(a.credit_not_covered)+ sum(a.not_credit) + sum(a.cash) as amount_total
from (select min(ai.id) as id, p.country_id,
SUM(ai.amount_total) as credit_covered,
0.0 as credit_not_covered, 0.0 as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit > 0 and p.risk_insurance_grant_date is not null and
(ai.payment_mode_id is null or aj.type != 'cash') and ai.type = 'out_invoice'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, -SUM(ai.amount_total) as credit_covered,
0.0 as credit_not_covered, 0.0 as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit > 0 and p.risk_insurance_grant_date is not null and
(ai.payment_mode_id is null or aj.type != 'cash') and ai.type = 'out_refund'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
SUM(ai.amount_total) as credit_not_covered, 0.0 as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit > 0 and p.risk_insurance_grant_date is null and
(ai.payment_mode_id is null or aj.type != 'cash') and ai.type = 'out_invoice'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
-SUM(ai.amount_total) as credit_not_covered, 0.0 as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit > 0 and p.risk_insurance_grant_date is null and
(ai.payment_mode_id is null or aj.type != 'cash') and ai.type = 'out_refund'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
0.0 as credit_not_covered, SUM(ai.amount_total) as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit <= 0 and (ai.payment_mode_id is null or aj.type != 'cash')
and ai.type = 'out_invoice' and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
0.0 as credit_not_covered, -SUM(ai.amount_total) as not_credit, 0.0 as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and p.insurance_credit_limit <= 0 and (ai.payment_mode_id is null or aj.type != 'cash')
and ai.type = 'out_refund' and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
0.0 as credit_not_covered, 0.0 as not_credit, SUM(ai.amount_total) as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and aj.type = 'cash' and ai.type = 'out_invoice'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id
union
select min(ai.id) as id, p.country_id, 0.0 as credit_covered,
0.0 as credit_not_covered, 0.0 as not_credit, -SUM(ai.amount_total) as cash,
CAST(extract(year from ai.date_invoice)::int as text) as invoice_year, p.area_id,
extract(month from ai.date_invoice) as invoice_month, ai.state, p.user_id
from account_invoice ai inner join res_partner p on p.id = ai.partner_id
left join account_payment_mode pm on pm.id = ai.payment_mode_id
left join account_journal aj on aj.id = pm.fixed_journal_id
where ai.company_id = 1 and aj.type = 'cash' and ai.type = 'out_refund'
and ai.state in ('open', 'paid')
group by p.country_id, extract(year from ai.date_invoice)::int,
extract(month from ai.date_invoice), ai.state, p.user_id, p.area_id) a
group by a.country_id, a.invoice_month, a.invoice_year, a.state, a.user_id,
a.area_id)
""")
