from odoo import http
from odoo.http import request


class PremiumWaveWebsite(http.Controller):

    @http.route(['/patients'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_patients(self, **kwargs):
        return request.redirect('/')

    @http.route(['/providers'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_providers(self, **kwargs):
        return request.render('premium_wave_website.providers_page')

    @http.route(['/before-after'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_before_after(self, **kwargs):
        return request.render('premium_wave_website.before_after_page')

    @http.route(['/find-a-provider'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_find_provider(self, **kwargs):
        return request.render('premium_wave_website.find_provider_page')

    @http.route(['/about-us'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_about(self, **kwargs):
        return request.render('premium_wave_website.about_page')

    @http.route(['/contact-us'], type='http', auth='public', website=True, sitemap=True)
    def premium_wave_contact(self, **kwargs):
        values = {
            'sent': kwargs.get('sent'),
            'audience': kwargs.get('audience', 'patient'),
        }
        return request.render('premium_wave_website.contact_page', values)
