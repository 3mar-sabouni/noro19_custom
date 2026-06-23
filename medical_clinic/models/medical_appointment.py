from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta
from odoo.fields import Datetime
from odoo.tools import float_compare
from odoo.exceptions import UserError
import pytz



class MedicalAppointment(models.Model):
    _name = 'medical.appointment'
    _description = 'Medical Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'
    display_name = fields.Char(
        compute="_compute_display_name",
        store=True
    )
    # appointment_end = fields.Datetime(
    # string="Appointment End",
    # compute="_compute_appointment_end",
    # store=True
    # )





    patient_id = fields.Many2one(
        'res.partner',
        string='Patient',
        required=True,
        domain="[('is_patient', '=', True)]"
    )

    user_name = fields.Char(
        string="Responsible",
        default=lambda self: self.env.user.name
    )

    patient_no = fields.Char(
        string='Patient No.',
        help="Type or select Patient No."
    )

    gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female')],
        string='Gender'
    )

    age = fields.Integer(string='Age')

    mobile = fields.Char(
        related='patient_id.phone',
        string="Mobile",
        store=True
    )

    appointment_no = fields.Char(
        string='Appointment No.',
        readonly=True,
        copy=False
    )

    appointment_date = fields.Datetime(
        string='Date',
        required=True,
        store=True,
        help="Date when the appointment is scheduled"
    )

    urgency = fields.Selection(
        [('normal', 'Normal'), ('urgent', 'Urgent')],
        string='Treatment Type'
    )

    patient_categ = fields.Selection(
        [('old', 'Old'), ('new', 'New')],
        string='Patient Category'
    )

    treatments = fields.Many2many(
        'treatment.category',
        string='Treatments Category'
    )
    slot_duration = fields.Selection(
    [
        ('15', '15 Minutes'),
        ('30', '30 Minutes'),
        ('60', '1 Hour'),
        ('120', '2 Hours'),
    ],
    string="Slot Duration",
    default='30',
    required=True
)
    appointment_end = fields.Datetime(
    string="Appointment End",
    compute="_compute_appointment_end",
    store=True
)

    doctor_id = fields.Many2one(
        'hr.employee',
        string='Doctor',
        required=True,
        domain="[('is_doctor', '=', True)]"
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('in_progress', 'In Progress'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled')
        ],
        string='Status',
        default='draft',
        tracking=True
    )

    time_shift_ids = fields.Many2many(
        'medical.time.shift',
        string="Available Times",
        compute='_compute_time_shifts'
    )

    shift_id = fields.Many2one(
        'medical.time.shift',
        string="Booking Time",
        domain="[('id','in',time_shift_ids)]",
        help="Choose the time shift"
    )

    # -------------------------------------------------------------------------
    # VALIDATION   
    # -------------------------------------------------------------------------
    @api.constrains('appointment_date')
    def _check_past_date(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.appointment_date and rec.appointment_date < now:
                raise ValidationError(
                    _("You cannot create an appointment in the past.")
                )
    @api.depends('appointment_date', 'slot_duration')
    def _compute_appointment_end(self):
        for rec in self:
            if rec.appointment_date and rec.slot_duration:
                rec.appointment_end = rec.appointment_date + timedelta(
                    minutes=int(rec.slot_duration)
                )
            else:
                rec.appointment_end = False
    @api.constrains('appointment_date', 'doctor_id')
    def _check_doctor_rules(self):
        for rec in self:
            if not rec.appointment_date or not rec.doctor_id:
                continue

            # 1️⃣ Overlap check (20 minutes)
            start = rec.appointment_date
            end = start + timedelta(minutes=20)

            overlap = self.search([
                ('id', '!=', rec.id),
                ('doctor_id', '=', rec.doctor_id.id),
                ('state', '!=', 'cancelled'),
                ('appointment_date', '<', end),
                ('appointment_date', '>=', start - timedelta(minutes=19)),
            ], limit=1)

            if overlap:
                raise ValidationError(
                    _("Doctor %s already has an appointment in this time slot.")
                    % rec.doctor_id.name
                )

            # 2️⃣ Shift time validation (FIXED)
        if not rec.shift_id:
            raise ValidationError(_("Please select a booking time shift."))

        appt_time = rec._get_local_appt_float_time(rec.appointment_date)

        shift = rec.shift_id
        start_time = shift.start_time
        end_time = shift.end_time

        # Normalize float inputs like 9.30 → 9.5
        start_time = int(start_time) + (start_time % 1) * 100 / 60
        end_time = int(end_time) + (end_time % 1) * 100 / 60

        # Overnight shift support
        if end_time <= start_time:
            end_time += 24
            if appt_time < start_time:
                appt_time += 24

        if not (start_time <= appt_time <= end_time):
            raise ValidationError(
                _("Appointment time must be within doctor's working shift.")
            )



    @api.depends('appointment_date', 'slot_duration')
    def _compute_appointment_end(self):
        for rec in self:
            if rec.appointment_date and rec.slot_duration:
                rec.appointment_end = rec.appointment_date + timedelta(
                    minutes=int(rec.slot_duration)
                )
            else:
                rec.appointment_end = False

    


    @api.onchange("appointment_date")
    def _onchange_appointment_date(self):
        if not self.appointment_date:
            return

        now = fields.Datetime.now()
        if self.appointment_date < now:
            self.appointment_date = False
            return {
                "warning": {
                    "title": _("Invalid Date"),
                    "message": _("You cannot select a past appointment date."),
                }
            }


    
    def write(self, vals):
        for rec in self:
            if rec.state == 'done' and any(
              field in vals for field in ['appointment_date', 'appointment_end']
                ):
              raise UserError(
                _("❌ You cannot modify or move a completed appointment.")
            )
            start = vals.get('appointment_date', rec.appointment_date)

            # 🟢 ONLY when calendar resized (end explicitly changed)
            if 'appointment_end' in vals and start:
                end = vals.get('appointment_end')

                if isinstance(start, str):
                    start = fields.Datetime.from_string(start)
                if isinstance(end, str):
                    end = fields.Datetime.from_string(end)

                duration = int((end - start).total_seconds() / 60)

                # 🔁 Snap to allowed slots
                if duration <= 15:
                    vals['slot_duration'] = '15'
                elif duration <= 30:
                    vals['slot_duration'] = '30'
                elif duration <= 60:
                    vals['slot_duration'] = '60'
                else:
                    vals['slot_duration'] = '120'

            # 🔒 Validate rules (safe for both form + calendar)
            rec._validate_doctor_time_rules(
                start,
                vals.get('doctor_id', rec.doctor_id.id),
                vals.get('shift_id', rec.shift_id.id),
                vals.get('appointment_end', rec.appointment_end),
                exclude_id=rec.id
            )

        return super().write(vals)





    def _check_shift_limit(self, appointment_date, shift_id, doctor_id, exclude_id=False):
        if not appointment_date or not shift_id or not doctor_id:
            return

        # Normalize appointment_date
        if isinstance(appointment_date, str):
            appointment_date = Datetime.from_string(appointment_date)

        # Normalize IDs → records
        shift = self.env['medical.time.shift'].browse(shift_id)
        doctor = self.env['hr.employee'].browse(doctor_id)

        start_day = appointment_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_day = appointment_date.replace(
            hour=23, minute=59, second=59, microsecond=0
        )

        domain = [
            ('appointment_date', '>=', start_day),
            ('appointment_date', '<=', end_day),
            ('shift_id', '=', shift.id),
            ('doctor_id', '=', doctor.id),
            ('state', '!=', 'cancelled'),
        ]

        if exclude_id:
            domain.append(('id', '!=', exclude_id))

        count = self.env['medical.appointment'].search_count(domain)

        if count >= 10:
            raise ValidationError(_(
                "Only 10 appointments are allowed for Dr. %(doctor)s "
                "in this shift on %(date)s."
            ) % {
                'doctor': doctor.display_name,
                'date': start_day.date(),
            })

    


 
    # ------------------------------------------------------------------    -------
    # CREATE
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            start = vals.get('appointment_date')
            slot = vals.get('slot_duration', '30')

            if start:
                if isinstance(start, str):
                    start = fields.Datetime.from_string(start)

                vals['appointment_end'] = start + timedelta(minutes=int(slot))

                self._validate_doctor_time_rules(
                    vals.get('appointment_date'),
                    vals.get('doctor_id'),
                    vals.get('shift_id'),
                    vals.get('appointment_end')
                )
            # self._check_shift_limit(
            #     vals.get('appointment_date'),
            #     vals.get('shift_id'),
            #     vals.get('doctor_id')
            # )

            if vals.get('patient_id'):
                patient = self.env['res.partner'].browse(vals['patient_id'])

                if not patient.patient_no or patient.patient_no == 'New':
                    patient_no = self.env['ir.sequence'].next_by_code(
                        'medical.patient'
                    ) or 'PAT/NEW'
                    patient.write({'patient_no': patient_no})
                    vals['patient_no'] = patient_no
                else:
                    vals['patient_no'] = patient.patient_no

                patient.write({
                    'is_patient': True,
                    'gender': vals.get('gender', patient.gender),
                    'patient_age': vals.get('age', patient.patient_age),
                    'phone': vals.get('phone', patient.phone),
                })

            if not vals.get('appointment_no'):
                vals['appointment_no'] = self.env['ir.sequence'].next_by_code(
                    'medical.appointment'
                ) or 'APT/NEW'

            if not vals.get('user_name'):
                vals['user_name'] = self.env.user.name

        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # WRITE (if date or shift is changed later)
    # -------------------------------------------------------------------------

   
            # rec._check_shift_limit(
            #         appointment_date,
            #         shift_id,
            #         doctor_id,
            #         exclude_id=rec.id
            #     )


        return super().write(vals)
    def _get_local_appt_float_time(self, appointment_date):
        """Convert appointment datetime → local float time"""
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        local_dt = appointment_date.astimezone(user_tz)
        return local_dt.hour + local_dt.minute / 60.0

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------
    @api.onchange('appointment_date', 'doctor_id')
    def _onchange_auto_select_shift(self):
        if not self.appointment_date or not self.doctor_id:
            self.shift_id = False
            return

        # Convert appointment time to LOCAL float time
        appt_time = self._get_local_appt_float_time(self.appointment_date)

        selected_shift = False

        for shift in self.doctor_id.time_shift_ids:
            start_time = shift.start_time
            end_time = shift.end_time

            # Normalize floats: 9.30 → 9.5
            start_time = int(start_time) + (start_time % 1) * 100 / 60
            end_time = int(end_time) + (end_time % 1) * 100 / 60

            check_time = appt_time

            # Overnight shift handling
            if end_time <= start_time:
                end_time += 24
                if check_time < start_time:
                    check_time += 24

            if start_time <= check_time <= end_time:
                selected_shift = shift
                break

        self.shift_id = selected_shift


    @api.onchange('patient_no')
    def _onchange_patient_no(self):
        if self.patient_no:
            patient = self.env['res.partner'].search(
                [('patient_no', '=', self.patient_no)],
                limit=1
            )
            if patient:
                self.patient_id = patient
                self.gender = patient.gender
                self.age = patient.patient_age
                
            else:
                self.patient_id = False
                self.gender = False
                self.age = False
                self.mobile = False

    @api.onchange('patient_id')
    def _onchange_patient_id(self):
        if self.patient_id:
            self.patient_no = self.patient_id.patient_no or ''
            self.gender = self.patient_id.gender
            self.age = self.patient_id.patient_age
        self.user_name = self.env.user.name


    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('doctor_id')
    def _compute_time_shifts(self):
        for record in self:
            record.time_shift_ids = self.env['medical.time.shift'].search([
                ('id', 'in', record.doctor_id.time_shift_ids.ids)
            ]).ids
    
    @api.depends('patient_id', 'patient_id.phone', 'appointment_no')
    def _compute_display_name(self):
        for rec in self:
            patient = rec.patient_id.name or ''
            mobile = rec.patient_id.phone or ''
            apt = rec.appointment_no or ''
            rec.display_name = f"{apt} | {patient} | {mobile}"

    # @api.depends('appointment_date')
    # def _compute_appointment_end(self):
    #     for rec in self:
    #         rec.appointment_end = (
    #             rec.appointment_date + timedelta(minutes=30)
    #             if rec.appointment_date else False
    #         )


    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    def _get_appt_end(self, start, slot_duration):
        return start + timedelta(minutes=int(slot_duration))

    def _validate_doctor_time_rules(
        self,
        appointment_date,
        doctor_id,
        shift_id,
        appointment_end=None,
        exclude_id=None
    ):
        """Validate doctor overlap + shift time (resize-safe)"""

        if not appointment_date or not doctor_id or not shift_id:
            return

        # Normalize datetime
        if isinstance(appointment_date, str):
            appointment_date = fields.Datetime.from_string(appointment_date)

        if appointment_end and isinstance(appointment_end, str):
            appointment_end = fields.Datetime.from_string(appointment_end)

        # Fallback: if end not provided → assume 30 min
        if not appointment_end:
            appointment_end = appointment_date + timedelta(minutes=30)

        doctor = self.env['hr.employee'].browse(doctor_id)
        shift = self.env['medical.time.shift'].browse(shift_id)

        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        local_start = appointment_date.astimezone(user_tz)
        local_end = appointment_end.astimezone(user_tz)

        # -----------------------------
        # 1️⃣ OVERLAP CHECK (REAL RANGE)
        # -----------------------------
        domain = [
            ('doctor_id', '=', doctor.id),
            ('state', '!=', 'cancelled'),
        ]

        if exclude_id:
            domain.append(('id', '!=', exclude_id))

        appointments = self.env['medical.appointment'].search(domain)

        for appt in appointments:
            appt_start = appt.appointment_date.astimezone(user_tz)
            appt_end = (
                appt.appointment_end.astimezone(user_tz)
                if appt.appointment_end
                else appt_start + timedelta(minutes=int(appt.slot_duration or 30))
            )

            # 🔴 REAL overlap condition
            if local_start < appt_end and local_end > appt_start:
                raise UserError(_(
                    "⚠️ Doctor %(doc)s already booked\n"
                    "%(start)s - %(end)s"
                ) % {
                    'doc': doctor.name,
                    'start': appt_start.strftime('%I:%M %p').lstrip('0'),
                    'end': appt_end.strftime('%I:%M %p').lstrip('0'),
                })

        # -----------------------------
        # 2️⃣ SHIFT VALIDATION
        # -----------------------------
        appt_time = self._get_local_appt_float_time(appointment_date)

        valid_shift = False
        for s in doctor.time_shift_ids:
            start_time = self._normalize_time(s.start_time)
            end_time = self._normalize_time(s.end_time)

            check_time = appt_time

            if end_time <= start_time:
                end_time += 24
                if check_time < start_time:
                    check_time += 24

            if start_time <= check_time <= end_time:
                valid_shift = s
                break

        if not valid_shift:
            raise UserError(_(
                "⏰ Appointment time %s is outside doctor's working hours"
            ) % self._float_time_to_12h(appt_time))


        if shift_id != valid_shift.id:
            self.shift_id = valid_shift.id



    def action_draft(self):
        for rec in self:
            if rec.state != '':
                continue
            rec.state = 'draft'

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            rec.state = 'confirmed'


    def action_open_patient_form(self):
        self.ensure_one()
        if self.state == 'confirmed':
            self.state = 'in_progress'
            return {
                'type': 'ir.actions.act_window',
                'name': 'Patient Form',
                'res_model': 'res.partner',
                'view_mode': 'form',
                'res_id': self.patient_id.id,
                'target': 'current',
            }

    def action_done(self):
        self.state = 'done'
    def _normalize_time(self, value):
        """Convert 9.30 → 9.5"""
        return int(value) + (value % 1) * 100 / 60

    def action_cancel(self):
        self.state = 'cancelled'
    # -------------------------------------------------------------------------
    # Onchange
    # -------------------------------------------------------------------------
    @api.onchange('appointment_date', 'doctor_id', 'shift_id')
    def _onchange_doctor_rules(self):
        for rec in self:

            if not rec.appointment_date or not rec.doctor_id:
                return

            warnings = []

            # 1️⃣ Overlap check (30 minutes)
            start = rec.appointment_date
            end = start + timedelta(minutes=30)

            overlap = self.env['medical.appointment'].search([
                ('id', '!=', rec.id),
                ('doctor_id', '=', rec.doctor_id.id),
                ('state', '!=', 'cancelled'),
                ('appointment_date', '<', end),
                ('appointment_date', '>=', start - timedelta(minutes=29)),
            ], limit=1)

            if overlap:
                warnings.append(
                    _("Doctor %s already has an appointment in this time slot.")
                    % rec.doctor_id.name
                )
                rec.appointment_date = False

            # 2️⃣ Shift validation
            if rec.appointment_date and rec.shift_id:

                appt_time = rec._get_local_appt_float_time(rec.appointment_date)

                shift = rec.shift_id
                start_time = shift.start_time
                end_time = shift.end_time

                # Normalize floats like 9.30 → 9.5
                start_time = int(start_time) + (start_time % 1) * 100 / 60
                end_time = int(end_time) + (end_time % 1) * 100 / 60

                # Overnight shift support
                if end_time <= start_time:
                    end_time += 24
                    if appt_time < start_time:
                        appt_time += 24

                if not (start_time <= appt_time <= end_time):
                    warnings.append(
                        _("Appointment time must be within doctor's working shift.")
                    )
                    rec.appointment_date = False

            if warnings:
                return {
                    'warning': {
                        'title': _("Invalid Appointment"),
                        'message': "\n".join(warnings),
                    }
                }
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
