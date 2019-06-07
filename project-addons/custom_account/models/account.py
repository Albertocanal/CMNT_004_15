# Copyright 2019 Omar Castiñeira, Comunitea Servicios Tecnológicos S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import models, fields, api, _, exceptions


class AccountMoveLine(models.Model):

    _inherit = 'account.move.line'

    scheme = fields.Selection([('CORE', 'Basic (CORE)'),
                               ('B2B', 'Enterprise (B2B)')], string='Scheme',
                              related="mandate_id.scheme", readonly=True)
    pner_vat = fields.Char("CIF/NIF/VAT", related="partner_id.vat",
                           readonly=True)

    last_rec_date = fields.Date(
        compute='_compute_last_rec_date',
        store=True,
        index=True,
        string='Last reconciliation date',
        help="The date of the last reconciliation (full) "
             "account move line."
    )

    @api.depends('full_reconcile_id.reconciled_line_ids.date')
    def _compute_last_rec_date(self):
        for line in self:
            if line.full_reconcile_id:
                move_lines = line.full_reconcile_id.reconciled_line_ids
                last_line = move_lines.sorted(lambda l: l.date)[-1]
                line.last_rec_date = last_line.date


class AccountInvoiceLine(models.Model):

    _inherit = 'account.invoice.line'

    purchase_supplier_reference = fields.Char(
        'Supplier reference', related='purchase_id.partner_ref',
        readonly=True)
    active = fields.Boolean(default=True)
    sale_order_id = fields.Many2one("sale.order", "Sale", readonly=True,
                                    related="sale_line_ids.order_id")
    cost_unit = fields.Float("Product cost price")


class AccountInvoice(models.Model):

    _inherit = 'account.invoice'

    @api.multi
    def _get_sale_order_ids(self):
        for invoice in self:
            invoice.sale_order_ids = invoice.invoice_line_ids.\
                mapped('sale_line_ids.order_id')

    attach_picking = fields.Boolean('Attach picking')
    sale_order_ids = fields.Many2many('sale.order', string='Sale Orders',
                                      compute="_get_sale_order_ids",
                                      readonly=True,
                                      help="This is the list of sale orders "
                                           "linked to this invoice. ")
    country_id = fields.Many2one('res.country', 'Country',
                                 related="commercial_partner_id.country_id",
                                 readonly=True, store=False)
    invoice_type_id = fields. \
        Many2one('res.partner.invoice.type', 'Invoice type', readonly=True,
                 related="commercial_partner_id.invoice_type_id")
    active = fields.Boolean(default=True)
    not_send_email = fields.Boolean("Not send email")
    total = fields.Float("Total Paid", compute="total_paid")
    last_payment = fields.Date("Last Payment", compute="last_payment_date")
    partner_commercial = fields.Many2one("res.users", String="Commercial",
                                         related="partner_id.user_id",
                                         readonly=True)

    date_due = fields.Date(states={'draft': [('readonly', False)],
                                   'open': [('readonly', False)]})
    state_web = fields.Char('State web', compute='_get_state_web', store=True)

    @api.multi
    @api.depends('state', 'payment_mode_id', 'payment_move_line_ids')
    def _get_state_web(self):
        for invoice in self:
            res = ''
            invoice_state = invoice.state
            if invoice.payment_mode_id:
                if invoice.state == 'open' and invoice.returned_payment:
                    res = 'returned'
                elif invoice.state == 'paid' \
                        and invoice.payment_mode_id.transfer_account_id \
                        and invoice.payment_mode_id.payment_method_id.code == \
                        'sepa_direct_debit':
                    res = invoice._check_payments()
                else:
                    res = invoice_state
            else:
                res = invoice_state

            invoice.state_web = res

    @api.multi
    def _check_payments(self):
        self.ensure_one()
        res = ''
        for payment in self.payment_move_line_ids:
            for payment_account in payment.move_id.line_ids:
                if payment_account.account_id.id == \
                        self.payment_mode_id.transfer_account_id.id:
                    for reconcile_line in payment_account.full_reconcile_id.\
                            reconciled_line_ids:
                        if reconcile_line.move_id != payment.move_id and \
                                reconcile_line.credit != 0:
                            res = 'paid'
                            return res
                else:
                    res = 'remitted'
        return res

    @api.onchange('user_id')
    def onchage_user_id(self):
        if self.user_id:
            team_obj = self.env['crm.team']
            self.team_id = team_obj.search([('member_ids', 'in',
                                             [self.user_id.id])])

    @api.multi
    def total_paid(self):
        for invoice in self:
            if invoice.state in ('open', 'paid'):
                invoice.total = invoice.amount_total - invoice.residual
            else:
                invoice.total = 0.0

    @api.multi
    def last_payment_date(self):
        for invoice in self:
            if invoice.payment_move_line_ids:
                invoice.last_payment = \
                    invoice.payment_move_line_ids[0].date

    @api.model
    def create(self, vals):
        if vals.get('partner_id', False):
            partner = self.env["res.partner"].browse(vals["partner_id"])
            if partner.commercial_partner_id.attach_picking:
                vals["attach_picking"] = \
                    partner.commercial_partner_id.attach_picking
        return super().create(vals)

    @api.onchange('partner_id', 'company_id')
    def _onchange_partner_id(self):
        result = super()._onchange_partner_id()
        company_id = self.company_id.id
        p = self.partner_id if not company_id else \
            self.partner_id.with_context(force_company=company_id)
        if p:
            self.attach_picking = p.commercial_partner_id.attach_picking
            self.team_id = p.commercial_partner_id.team_id.id
            self.currency_id = p.commercial_partner_id.\
                property_purchase_currency_id.id or self.env.user.company_id.currency_id.id
        return result

    @api.multi
    @api.returns('account.move.line')
    def _get_payment(self):
        self.ensure_one()
        payments = self.env['account.move.line']
        if self.type == "out_invoice" and self.sale_order_ids:
            payments = self.sale_order_ids.mapped('payment_line_ids')
        return payments

    @api.multi
    def action_move_create(self):
        res = super().action_move_create()
        for inv in self:
            inv.move_id.line_ids.\
                write({'blocked': inv.payment_mode_id.blocked or
                       inv.payment_term_id.blocked})
            payment_move_lines = inv._get_payment()
            for payment_line in payment_move_lines:
                inv.assign_outstanding_credit(payment_line.id)
        return res

    @api.multi
    def write(self, vals):
        res = super().write(vals)
        if vals.get('payment_mode_id', False):
            for inv in self:
                if inv.move_id and inv.payment_mode_id.blocked:
                    inv.move_id.line_ids.\
                        write({'blocked': inv.payment_mode_id.blocked})
        elif vals.get('payment_term_id', False):
            for inv in self:
                if inv.move_id and inv.payment_term_id.blocked:
                    inv.move_id.line_ids.\
                        write({'blocked': inv.payment_term_id.blocked})
        return res

    @api.multi
    def invoice_validate(self):
        res = super().invoice_validate()
        for inv in self:
            for line in inv.invoice_line_ids:
                line.write({'cost_unit': line.product_id.standard_price})
        return res

    @api.model
    def _get_first_invoice_fields(self, invoice):
        res = super()._get_first_invoice_fields(invoice)
        res.update({'team_id': invoice.team_id.id})
        return res

    @api.multi
    @api.onchange('date_due')
    def onchange_date_due(self):
        if self.state == 'open':
            return {'warning': {
                'title': _('Warning'),
                'message':
                _('Remember to change due date in associated payment(s)')
            }}


class PaymentMode(models.Model):

    _inherit = 'account.payment.mode'

    blocked = fields.Boolean('No Follow-up')


class AccountPaymentTerm(models.Model):

    _inherit = "account.payment.term"

    blocked = fields.Boolean('No Follow-up')


class AccountInvoiceRefund(models.TransientModel):

    _inherit = "account.invoice.refund"

    @api.multi
    def compute_refund(self, mode='refund'):
        res = super().compute_refund(mode=mode)
        if mode == "modify":
            new_invoices = []
            inv_obj = self.env['account.invoice']
            orig_invoice = inv_obj.browse(self.env.context['active_ids'][0])
            for tup in res['domain']:
                if tup[0] == "id":
                    new_invoices = inv_obj.browse(tup[2])
                    break
            for new_invoice in new_invoices:
                new_invoice.\
                    write({'user_id': orig_invoice.user_id.id or False,
                           'team_id': orig_invoice.team_id.id or False,
                           'partner_bank_id': orig_invoice.partner_bank_id.id
                           or False,
                           'mandate_id': orig_invoice.mandate_id.id or False,
                           'payment_mode_id': orig_invoice.payment_mode_id.id
                           or False})
        return res


class InvoiceMerge(models.TransientModel):
    _inherit = "invoice.merge"

    @api.model
    def _dirty_check(self):
        res = super()._dirty_check()
        if self.env.context.get('active_model', '') == 'account.invoice':
            invs = self.env['account.invoice'].\
                browse(self.env.context['active_ids'])
            for d in invs:
                if d['payment_term_id'] != invs[0]['payment_term_id']:
                    raise exceptions.Warning(
                        _('Not all invoices have the same payment term!'))
                if d['payment_mode_id'] != invs[0]['payment_mode_id']:
                    raise exceptions.Warning(
                        _('Not all invoices use the same payment mode!'))
                if d['user_id'] != invs[0]['user_id']:
                    raise exceptions.Warning(
                        _('Not all invoices are at the same salesperson!'))
                if d['team_id'] != invs[0]['team_id']:
                    raise exceptions.Warning(
                        _('Not all invoices are at the same sales team!'))
                if d['invoice_type_id'] != invs[0]['invoice_type_id']:
                    raise exceptions.Warning(
                        _('Not all invoices are of the same invoice type!'))
        return res
