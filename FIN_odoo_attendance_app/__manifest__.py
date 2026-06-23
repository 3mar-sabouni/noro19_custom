# -*- coding: utf-8 -*-
{
    'name': 'FIN Attendance',
    'version': '19.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Mobile attendance tracking with GPS, analytics, and time-off management',
    'description': """
FIN Attendance - Mobile Employee Attendance System
========================================================

Features:
---------
* Mobile app authentication with device binding
* GPS-enabled check-in/check-out with reverse geocoding  
* Analytic account selection per attendance
* Optional selfie capture for attendance verification
* Time-off request submission from mobile
* Leave balance tracking
* Bilingual support (English/Arabic)
* REST API for Flutter mobile application

Technical:
----------
* JWT-based authentication
* bcrypt password hashing
* Device binding (one device per employee)
* Extends hr.attendance and account.analytic.account models
* Custom REST API controllers
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'hr',
        'hr_attendance',
        'hr_holidays',
        'hr_expense',
        'analytic',
    ],
    'external_dependencies': {
        'python': ['jwt', 'bcrypt', 'requests'],
    },
    'data': [
        'security/fin_attendance_groups.xml',
        'security/ir.model.access.csv',
        'security/odoo_attendance_security.xml',
        'data/sequence.xml',
        'data/cron.xml',
        'views/odoo_attendance_employee_views.xml',
        'views/vehicle_views.xml',
        'views/fleet_trip_views.xml',
        'views/odoo_attendance_session_views.xml',
        'views/hr_attendance_views.xml',
        'views/account_analytic_views.xml',
        'views/app_config_views.xml',
        'views/attachment_views.xml',
        'views/attachment_batch_actions.xml',
        'views/inbox_message_views.xml',
        'views/hr_employee_extension_views.xml',
        'views/employee_task_views.xml',
        'views/menu_items.xml',
        'data/fin_attendance_group_sync.xml',
    ],
    'demo': [],
    'assets': {
        'web.assets_backend': [
            'FIN_odoo_attendance_app/static/src/xml/fleet_dashboard.xml',
            'FIN_odoo_attendance_app/static/src/xml/task_dashboard.xml',
            'FIN_odoo_attendance_app/static/src/js/fleet_dashboard_action.js',
            'FIN_odoo_attendance_app/static/src/js/task_dashboard_action.js',
            'FIN_odoo_attendance_app/static/src/js/attendance_employee_list_controller.js',
            'FIN_odoo_attendance_app/static/src/js/task_status_graph_renderer.js',
            'FIN_odoo_attendance_app/static/src/css/fleet_dashboard.css',
            'FIN_odoo_attendance_app/static/src/css/task_dashboard.css',
            'FIN_odoo_attendance_app/static/src/css/task_update_history.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [],
    'post_init_hook': 'post_init_cleanup_transfer_actions',
}




