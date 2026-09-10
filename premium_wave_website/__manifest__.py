{
    "name": "Premium Wave Website",
    "summary": "Premium Sofwave-style patient and provider website for Odoo 19",
    "version": "19.0.3.5.0",
    "category": "Website/Theme",
    "author": "Custom",
    "license": "LGPL-3",
    "depends": ["website"],
    "data": [
        "views/layout.xml",
        "views/homepage.xml",
        "views/providers.xml",
        "views/before_after.xml",
        "views/find_provider.xml",
        "views/about.xml",
        "views/contact.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "premium_wave_website/static/src/scss/premium_wave_v3.scss",
            "premium_wave_website/static/src/scss/premium_wave_mobile_content_fix.scss",
            "premium_wave_website/static/src/js/premium_wave_v3.js",
        ],
    },
    "installable": True,
    "application": False,
}
