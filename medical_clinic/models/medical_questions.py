# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MedicalQuestions(models.Model):
    _name = 'medical.questions'
    _description = 'Medical Questions'
    _rec_name = 'question'

    question = fields.Char(string='Question')

    @api.model_create_multi
    def create(self, vals_list):
        records = super(MedicalQuestions, self).create(vals_list)
        for rec in records:
            # create a template questionnaire row (no patient) if desired
            self.env['medical.questionnaire'].create({'question_id': rec.id})
        return records

    def unlink(self):
        for rec in self:
            lines = self.env['medical.questionnaire'].search([('question_id', '=', rec.id)])
            if lines:
                lines.unlink()
        return super(MedicalQuestions, self).unlink()
