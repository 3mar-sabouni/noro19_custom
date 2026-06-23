{
    'name': "Medical Hospital Management",
    'summary': """
        Hospital management module used to manage hospital functionalities:
        prescriptions, patients, doctors, diagnosis, etc.
    """,
    'description': """
        Medical Hospital Management system covering:
        - Patient Registration
        - Medical Appointments
        - Doctors & Specialists
        - Teeth Chart
        - Diagnosis & Treatment
        - Prescriptions
        - Payment Logs
        - Medicine Master Data
        - Medical Time Shifts
    """,

    'author': "Alan Technologies",
    'company': "Alan Technologies",
    'maintainer': "Alan Technologies",
    'website': "https://alantechnologies.in/",
    'license': "AGPL-3",

    'category': 'Healthcare',
    'version': '19.0.1.0.0',

    # ✔ Updated for Odoo 19
    'depends': [
        'base',
        'hr',
        'account',
        'sale_management',   # Sale is replaced with sale_management in Odoo 19
        'product',
        'web',
        'stock',
        'image_hub'
    ],

    'data': [
        'data/patient_id_sequence.xml',
        'data/medical_specialist_data.xml',
        'data/treatment_category_data.xml',
        'data/medical_treatment_data.xml',
        'data/medical_time_shift_data.xml',
        'data/medicine_frequency_data.xml',

        
        'views/patient_view.xml',
        'views/medical_appointment_views.xml',
        'views/medical_doctor_views.xml',
        'views/medical_prescription_views.xml',
        'views/medical_payment_log_views.xml',
        'views/medical_treatment_views.xml',
        'views/treatment_category_views.xml',
        'views/medicine_frequency_views.xml',
        'views/medical_medicine_views.xml',
        'views/medical_questions_views.xml',
        'views/medical_specialist_views.xml',
        'views/medical_time_shift_views.xml',
        'views/medical_source_views.xml',

        'report/medical_prescription_report.xml',
        'report/medical_prescription_templates.xml',

        'security/medical_clinic_groups.xml',
        'security/ir.model.access.csv',
    ],

    'assets': {
        'web.assets_backend': [
            #  'medical_hospital/static/src/js/calendar_time_limit.js',
            # Add your JS, CSS, Owl components if needed
            # 'your_module/static/src/js/custom.js',
            # 'your_module/static/src/css/style.css'
                "medical_clinic/static/src/js/calendar_patch.js",
                "medical_clinic/static/src/js/datetime_30_minute.js",
                "medical_clinic/static/src/js/appointment_form_close.js",
                "medical_clinic/static/src/css/calendar.css",
                "medical_clinic/static/src/js/global_delete_confirm.js",
        ],
    },

    'images': ['static/description/banner.png'],

    'installable': True,
    'application': True,
    'auto_install': False,
}
