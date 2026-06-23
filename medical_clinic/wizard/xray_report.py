from odoo import fields, models

class XRayReport(models.Model):
    """To add the x-ray report of the patients"""
    _name = 'xray.report'
    _description = 'X-Ray Report'

    patient_id = fields.Many2one('res.partner',
                                 string='Patient', required=True,
                                 help="name of the patient")
    report_date = fields.Date(string='Report Date',
                              default=lambda self: fields.Date.context_today(self),
                              required=True,
                              help="date of report adding")
    # report_file = fields.Binary(string='Report File', required=True,store=True,
    #                             help="File to upload")
    # file_name = fields.Char(string="File Name",
    #                         help="Name of the file")
    description = fields.Text(string='Description',
                              help="To add the description of the x-ray report")
    scan_image = fields.Binary(
        string="Scan Image", attachment=True,
        help="Upload an image of the scanned report (e.g., X-ray, MRI)."
    )
    image_filename = fields.Char(string="Image Filename")
