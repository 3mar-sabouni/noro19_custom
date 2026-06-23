# -*- coding: utf-8 -*-
import base64
import io
import zipfile

from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @staticmethod
    def _dedupe_filename(name, used_names):
        filename = (name or '').strip() or 'attachment'
        if filename not in used_names:
            used_names.add(filename)
            return filename

        dot = filename.rfind('.')
        if dot > 0:
            base = filename[:dot]
            ext = filename[dot:]
        else:
            base = filename
            ext = ''
        index = 2
        candidate = f'{base} ({index}){ext}'
        while candidate in used_names:
            index += 1
            candidate = f'{base} ({index}){ext}'
        used_names.add(candidate)
        return candidate

    def action_download_selected_zip(self):
        if not self:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No selection',
                    'message': 'Select one or more attachments first.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        file_buffer = io.BytesIO()
        filenames = set()
        included = 0
        with zipfile.ZipFile(file_buffer, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
            for attachment in self.sudo():
                if attachment.type != 'binary' or not attachment.datas:
                    continue
                try:
                    payload = base64.b64decode(attachment.datas)
                except Exception:
                    continue
                if not payload:
                    continue
                safe_name = self._dedupe_filename(attachment.name, filenames)
                archive.writestr(safe_name, payload)
                included += 1

        if not included:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No downloadable files',
                    'message': 'Selected records do not contain downloadable binary attachments.',
                    'type': 'warning',
                    'sticky': False,
                },
            }

        timestamp = fields.Datetime.now().strftime('%Y%m%d_%H%M%S')
        zip_attachment = self.sudo().create({
            'name': f'task_attachments_{timestamp}.zip',
            'type': 'binary',
            'datas': base64.b64encode(file_buffer.getvalue()),
            'mimetype': 'application/zip',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % zip_attachment.id,
            'target': 'self',
        }

    def action_delete_selected(self):
        if not self:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No selection',
                    'message': 'Select one or more attachments first.',
                    'type': 'warning',
                    'sticky': False,
                },
            }
        self.sudo().unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
