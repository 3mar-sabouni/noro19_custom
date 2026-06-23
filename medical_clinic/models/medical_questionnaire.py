# -*- coding: utf-8 -*-
from odoo import fields, models


class MedicalQuestionnaire(models.Model):
    _name = 'medical.questionnaire'
    _description = 'Medical Questionnaire'

    question_id = fields.Many2one('medical.questions', string='Question', help="Reference to master question")
    yes_no = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Yes or No')
    reason = fields.Text(string='Reason')
    patient_id = fields.Many2one('res.partner', string='Patient')
