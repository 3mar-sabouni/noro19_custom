# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, date,time
import pytz



class MedicalPrescription(models.Model):
    """Prescription of patient from the medical clinic"""
    _name = 'medical.prescription'
    _description = "Medical Prescription"
    _inherit = ['mail.thread']
    _rec_name = "sequence_no"

    sequence_no = fields.Char(string='Sequence No', required=True,
                              readonly=True, default=lambda self: _('New'),
                              help="Sequence number of the medical prescription")
    appointment_ids = fields.Many2many('medical.appointment',
                                       string="Appointment",
                                       compute="_compute_appointment_ids",
                                       help="All appointments created")
    appointment_id = fields.Many2one('medical.appointment',
                                     string="Appointment",
                                     domain="[('id','in',appointment_ids)]",
                                     required=True,
                                     help="All appointments created")
    patient_id = fields.Many2one(related="appointment_id.patient_id",
                                 string="Patient",
                                 required=True,
                                 help="name of the patient")
    # token_no = fields.Integer(related="appointment_id.token_no",
    #                           string="Token Number",
    #                           help="Token number of the patient")
    treatment_id = fields.Many2one('medical.treatment',
                                   string="Treatment",
                                   help="Name of the treatment done for patient")
    cost = fields.Float(related="treatment_id.cost",
                        string="Treatment Cost",
                        help="Cost of treatment")
    currency_id = fields.Many2one('res.currency', 'Currency',
                                  default=lambda self: self.env.user.company_id.currency_id,
                                  required=True,
                                  help="To add the currency type in cost")
    prescribed_doctor_id = fields.Many2one(related="appointment_id.doctor_id",
                                           string='Prescribed Doctor',
                                           required=True,
                                           help="Doctor who is prescribed")
    prescription_date = fields.Date(default=fields.Date.today,
                                string='Prescription Date',
                                required=True,
                                help="Date of the prescription")
    state = fields.Selection([('new', 'New'),
                              ('done', 'Prescribed'),
                              ('invoiced', 'Invoiced')],
                             default="new",
                             string="state",
                             help="state of the appointment")
    medicine_ids = fields.One2many('medical.prescription_lines',
                                   'prescription_id',
                                   string="Medicine",
                                   help="medicines")
    invoice_data_id = fields.Many2one(comodel_name="account.move", string="Invoice Data",
                                      help="Invoice Data")
    treatment_invoice_id = fields.Many2one('account.move', string="Treatment Invoice")
    prescription_invoice_id = fields.Many2one('account.move', string="Prescription Invoice")
    
    referred_doctor_id = fields.Many2one(
        'hr.employee', string='Referred Doctor',
        domain="[('is_doctor', '=', True)]",
        help="Select a different doctor if referring the patient"
    )
    next_appointment_date = fields.Datetime(
    string="Next Appointment Date & Time",
    help="Date and time for the next appointment"
    )
    # grand_total = fields.Float(compute="_compute_grand_total",
    #                            string="Grand Total",
    #                            help="Get the grand total amount")

    @api.model_create_multi
    def create(self, vals):
        """Ensure the next appointment is updated/created when a prescription is created."""
        vals = vals[0]
        if vals.get('sequence_no', _('New')) == _('New'):
                vals['sequence_no'] = self.env['ir.sequence'].next_by_code('medical.prescriptions') or _('New')
        records = super(MedicalPrescription, self).create(vals)
        for record in records:
            record._update_or_create_appointment()
        return records

    def write(self, vals):
        """Ensure the next appointment is updated when a prescription is modified."""
        res = super(MedicalPrescription, self).write(vals)
        if 'next_appointment_date' in vals or 'referred_doctor_id' in vals:
            for record in self:
                record._update_or_create_appointment()
        return res

    def _update_or_create_appointment(self):
        """Create next appointment like a normal appointment with auto shift selection."""
        if not self.next_appointment_date or not self.patient_id:
            return

        # Determine the doctor: referred doctor or prescribed doctor
        doctor = self.referred_doctor_id or self.prescribed_doctor_id
        if not doctor:
            return

        # --- CONVERT TO LOCAL TIME FLOAT ---
        appt_dt = self.next_appointment_date
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Ensure datetime is timezone-aware
        if appt_dt.tzinfo is None:
            appt_dt = pytz.UTC.localize(appt_dt)

        local_dt = appt_dt.astimezone(user_tz)
        appt_time = local_dt.hour + local_dt.minute / 60.0

        # --- PICK SHIFT BASED ON APPOINTMENT TIME ---
        selected_shift = False
        for shift in doctor.time_shift_ids:
            # Normalize shift start/end times (float like 9.30 → 9.5)
            start_time = int(shift.start_time) + (shift.start_time % 1) * 100 / 60
            end_time = int(shift.end_time) + (shift.end_time % 1) * 100 / 60
            check_time = appt_time

            # Overnight shift support
            if end_time <= start_time:
                end_time += 24
                if check_time < start_time:
                    check_time += 24

            if start_time <= check_time <= end_time:
                selected_shift = shift
                break

        if not selected_shift:
            raise UserError(_(
            "⏰ Appointment time %s is outside doctor's working hours"
        ) % self._float_time_to_12h(appt_time))


        # --- VALIDATE TIME RULES (overlap + shift) ---
        self.env['medical.appointment']._validate_doctor_time_rules(
            appointment_date=self.next_appointment_date,
            doctor_id=doctor.id,
            shift_id=selected_shift.id,
            exclude_id=False
        )

        # --- CREATE NEXT APPOINTMENT ---
        self.env['medical.appointment'].create({
            'patient_id': self.patient_id.id,
            'appointment_date': self.next_appointment_date,
            'doctor_id': doctor.id,
            'shift_id': selected_shift.id,
            'state': 'draft',
        })





    @api.depends()
    def _compute_appointment_ids(self):
        today = fields.Date.today()

        start_dt = datetime.combine(today, time.min)
        end_dt = datetime.combine(today, time.max)

        appointments = self.env['medical.appointment'].search([
            ('state', '=', 'confirmed'),
            ('appointment_date', '>=', start_dt),
            ('appointment_date', '<=', end_dt),
        ])

        for rec in self:
            rec.appointment_ids = appointments.ids


    def action_prescribed(self):
        """Marks the prescription and its associated appointment as `done`.
        This method updates the state of both the MedicalPrescription instance
        and its linked medical.appointment instance to `done`, indicating that
        the prescription has been finalized and the appointment has been completed.
        """
        self.state = 'done'
        self.appointment_id.state = 'done'

    def create_invoice(self):
        """Create two separate invoices: one for treatment and one for prescribed medicines."""
        self.ensure_one()

        if not self.treatment_id:
            raise UserError(_("No treatment selected."))

        # ---------- TREATMENT INVOICE ----------
        treatment_invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.id,
            'state': 'draft',
            'invoice_line_ids': [
                fields.Command.create({
                    'name': self.treatment_id.name,
                    'quantity': 1,
                    'price_unit': self.cost,
                })
            ],
            'is_treatment_invoice': True,
        }
        treatment_invoice = self.env['account.move'].create(treatment_invoice_vals)

        # ---------- PRESCRIPTION INVOICE ----------
        medicine_invoice_lines = []
        medicine_moves = []
        for rec in self.medicine_ids:
            product = self.env['product.product'].search([
                ('product_tmpl_id', '=', rec.medicament_id.id)], limit=1)
            if product:
                # Add medicine line
                medicine_invoice_lines.append(
                    fields.Command.create({
                        'product_id': product.id,
                        'name': rec.display_name,
                        'quantity': rec.quantity,
                        'price_unit': rec.price,
                    })
                )

                # Track movement if stockable
                if product.type == 'consu':
                    medicine_moves.append({ 
                        'product_id': product,
                        'quantity': rec.quantity,
                    })

        if not medicine_invoice_lines:
            raise UserError(_("No valid medicines to invoice."))

        prescription_invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.id,
            'state': 'draft',
            'invoice_line_ids': medicine_invoice_lines,
        }
        prescription_invoice = self.env['account.move'].create(prescription_invoice_vals)

        # ---------- STOCK MOVEMENT ----------
        if medicine_moves:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            if not warehouse:
                raise UserError(_('No warehouse found for the company. Please configure a warehouse.'))

            source_location = warehouse.lot_stock_id
            customer_location = self.env.ref('stock.stock_location_customers')

            for move in medicine_moves:
                self.env['stock.move'].create({
                    'origin': f'Prescription {self.sequence_no}',
                    'product_id': move['product_id'].id,
                    'product_uom_qty': move['quantity'],
                    'quantity': move['quantity'],
                    'product_uom': move['product_id'].uom_id.id,
                    'location_id': source_location.id,
                    'location_dest_id': customer_location.id,
                    'state': 'done',
                })

        # Link only treatment invoice (or both if needed)
        self.invoice_data_id = treatment_invoice.id
        self.state = 'invoiced'

        # ---------- RETURN BOTH INVOICES ----------
        return {
            'type': 'ir.actions.act_window',
            'name': 'Treatment & Prescription Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', [treatment_invoice.id, prescription_invoice.id])],
            'context': "{'move_type':'out_invoice'}",
        }

    def action_view_invoice(self):
        """Invoice view"""
        return {
            'name': _('Customer Invoice'),
            'view_mode': 'form',
            'view_id': self.env.ref('account.view_move_form').id,
            'res_model': 'account.move',
            'context': "{'move_type':'out_invoice'}",
            'type': 'ir.actions.act_window',
            'res_id': self.invoice_data_id.id,
        }
    def action_print_prescription(self):
        return self.env.ref('medical_clinic.report_pdf_medical_prescription').report_action(self)

    def action_open_patient_payments(self):
        self.ensure_one()
        return self.patient_id.with_context({
            'default_treatment_name': self.treatment_id.name,
            'default_treatment_cost': self.cost
        }).action_open_patient_payments()
    def _float_time_to_12h(self, float_time):
        """Convert float time (e.g. 23.75) to 12-hour format (11:45 PM)"""
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))

        if minutes == 60:
            hours += 1
            minutes = 0

        suffix = 'AM' if hours < 12 else 'PM'
        display_hour = hours % 12 or 12

        return f"{display_hour}:{minutes:02d} {suffix}"




class MedicalPrescriptionLines(models.Model):
    """Prescription lines of the medical clinic prescription"""
    _name = 'medical.prescription_lines'
    _description = "Medical Prescriptions Lines"
    _rec_name = "medicament_id"

    medicament_id = fields.Many2one('product.template',
                                    domain="[('is_medicine', '=', True)]",
                                    string="Medicament",
                                    help="Name of the medicine")
    generic_name = fields.Char(string="Generic Name",
                               related="medicament_id.generic_name",
                               help="Generic name of the medicament")
    dosage_strength = fields.Integer(string="Dosage Strength",
                                     related="medicament_id.dosage_strength",
                                     help="Dosage strength of medicament")
    medicament_form = fields.Selection([('tablet', 'Tablets'),
                             ('capsule', 'Capsules'),
                             ('liquid', 'Liquid'),
                             ('injection', 'Injections')],
                            string="Medicament Form",
                            required=True,
                            help="Add the form of the medicine")
    quantity = fields.Integer(string="Quantity",
                              required=True,
                              help="Quantity of medicine")
    # frequency_id = fields.Many2one('medicine.frequency',
    #                                string="Frequency",
    #                                required=True,
    #                                help="Frequency of medicine")
    price = fields.Float(related='medicament_id.list_price',
                          string="Price",
                          help="Cost of medicine")
    prescription_id = fields.Many2one('medical.prescription',
                                      help="Relate the model with medical_prescription")
    morning = fields.Boolean(string="Morning")
    noon = fields.Boolean(string="After Noon")
    night = fields.Boolean(string="Night")
    medicine_take = fields.Selection([
        ('before', 'Before Food'),
        ('after', 'After Food')
    ], string='Medicine Take',default='after')
    days = fields.Float(string='Days')




