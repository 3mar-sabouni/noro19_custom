from odoo import models, fields, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    move_id = fields.Many2one('account.move', string="Related Invoice")
    treatment_name = fields.Char(string="Treatment Done")
    treatment_cost = fields.Float(string="Actual Cost")
    amount_due = fields.Float(string="Balance", compute="_compute_amount_due", store=True)
    patient_sign = fields.Char(string="Patient Sign")

    @api.depends('partner_id')
    def _compute_amount_due(self):
        for record in self:
            if record.partner_id:
                invoices = self.env['account.move'].search([
                    ('partner_id', '=', record.partner_id.id),
                    ('move_type', '=', 'out_invoice'),
                    ('is_treatment_invoice', '=', True),
                    ('state', '=', 'posted'), ('payment_state', '!=', 'paid')
                ])
                print("invoices",[invoices])

                for inv in invoices:
                    for line in inv.invoice_line_ids:
                        record.treatment_name = line.name
                    paid = sum(inv.amount_total - inv.amount_residual for inv in invoices)
                    total = sum(inv.amount_total for inv in invoices)
                    record.treatment_cost = inv.amount_total
                    record.amount_due = total - paid
            else:
                record.amount_due = 0.0
