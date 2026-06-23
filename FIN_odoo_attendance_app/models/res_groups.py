# -*- coding: utf-8 -*-
from odoo import models


class ResGroups(models.Model):
    _inherit = 'res.groups'

    def _fin_attendance_field_value(self, record, field_name):
        field = self._fields.get(field_name)
        value = record[field_name]
        if field and field.type == 'many2one':
            return value.id if value else False
        return value or False

    def _fin_attendance_sync_menus(self, manager_group, user_group=None):
        root_menu = self.env.ref('FIN_odoo_attendance_app.menu_odoo_attendance_root', raise_if_not_found=False)
        system_group = self.env.ref('base.group_system', raise_if_not_found=False)
        manager_menu_group_ids = [manager_group.id]
        fleet_tasks_menu_group_ids = [manager_group.id]
        if user_group:
            fleet_tasks_menu_group_ids.append(user_group.id)
        if system_group:
            manager_menu_group_ids.append(system_group.id)
            fleet_tasks_menu_group_ids.append(system_group.id)

        manager_only_menu_xmlids = (
            'FIN_odoo_attendance_app.menu_odoo_attendance_employees',
            'FIN_odoo_attendance_app.menu_odoo_attendance_sessions',
            'FIN_odoo_attendance_app.menu_odoo_attendance_attendance',
            'FIN_odoo_attendance_app.menu_odoo_attendance_hr_attendance',
            'FIN_odoo_attendance_app.menu_odoo_attendance_config',
            'FIN_odoo_attendance_app.menu_odoo_attendance_messages',
        )
        fleet_tasks_menu_xmlids = (
            'FIN_odoo_attendance_app.menu_odoo_attendance_fleet',
            'FIN_odoo_attendance_app.menu_odoo_attendance_fleet_dashboard',
            'FIN_odoo_attendance_app.menu_odoo_attendance_vehicles',
            'FIN_odoo_attendance_app.menu_odoo_attendance_trips',
            'FIN_odoo_attendance_app.menu_odoo_attendance_tasks',
            'FIN_odoo_attendance_app.menu_odoo_attendance_tasks_list',
            'FIN_odoo_attendance_app.menu_odoo_attendance_tasks_dashboard',
            'FIN_odoo_attendance_app.menu_odoo_attendance_tasks_timeline',
        )

        for menu_xmlid in manager_only_menu_xmlids:
            menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            if menu:
                menu.sudo().write({'group_ids': [(6, 0, manager_menu_group_ids)]})

        for menu_xmlid in fleet_tasks_menu_xmlids:
            menu = self.env.ref(menu_xmlid, raise_if_not_found=False)
            if menu:
                menu.sudo().write({'group_ids': [(6, 0, fleet_tasks_menu_group_ids)]})

        if root_menu:
            root_values = {
                'group_ids': [(6, 0, fleet_tasks_menu_group_ids)],
                'action': False,
            }
            if 'web_icon' in root_menu._fields:
                root_values['web_icon'] = 'FIN_odoo_attendance_app,static/description/icon.png'
            if 'web_icon_data' in root_menu._fields:
                root_values['web_icon_data'] = False
            root_menu.sudo().write(root_values)

        clear_caches = getattr(self.env['ir.ui.menu'], 'clear_caches', None)
        if clear_caches:
            clear_caches()

    def _fin_attendance_sync_category(self):
        user_group = self.env.ref('FIN_odoo_attendance_app.group_fin_attendance_user', raise_if_not_found=False)
        manager_group = self.env.ref('FIN_odoo_attendance_app.group_fin_attendance_manager', raise_if_not_found=False)
        if not manager_group:
            return True

        manager_values = {'name': 'Administrator'}
        user_values = {'name': 'User'}

        if 'category_id' in self._fields:
            category = self.env.ref(
                'FIN_odoo_attendance_app.module_category_fin_attendance',
                raise_if_not_found=False,
            )
            manager_values['category_id'] = category.id if category else False
            user_values['category_id'] = category.id if category else False

        if 'privilege_id' in self._fields:
            privilege = self.env.ref(
                'FIN_odoo_attendance_app.privilege_fin_attendance',
                raise_if_not_found=False,
            )
            manager_values['privilege_id'] = privilege.id if privilege else False
            user_values['privilege_id'] = privilege.id if privilege else False

        manager_dirty = manager_group.name != manager_values['name']
        for field_name, field_value in manager_values.items():
            if field_name == 'name':
                continue
            current_value = self._fin_attendance_field_value(manager_group, field_name)
            manager_dirty = manager_dirty or current_value != field_value
        if manager_dirty:
            manager_group.sudo().write(manager_values)

        if user_group and user_values:
            user_dirty = False
            for field_name, field_value in user_values.items():
                current_value = self._fin_attendance_field_value(user_group, field_name)
                user_dirty = user_dirty or current_value != field_value
            if user_dirty:
                user_group.sudo().write(user_values)

        self._fin_attendance_sync_menus(manager_group, user_group)

        update_user_groups_view = getattr(self.env['res.groups'], '_update_user_groups_view', None)
        if update_user_groups_view:
            update_user_groups_view()
        return True
