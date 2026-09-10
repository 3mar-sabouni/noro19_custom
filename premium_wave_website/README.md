# Premium Wave Website — Odoo 19 V3

V3 continues the Odoo 19 recreation with a much more complete patient/provider journey.

## Added in V3
- Interactive treatment-area explorer with hotspots
- Full Before & After page with draggable comparisons and category filters
- Extended Providers page with benefits, support, testimonial and webinar/demo sections
- Functional provider-finder prototype with live client-side search and a map-style panel
- Custom About page
- Custom Patient / Provider contact experience with tab switching and FAQ accordion
- Multi-slide patient testimonial component
- Editorial / journal cards
- Floating quick-contact widget
- Stronger mobile responsive behavior
- Same premium reference assets/style used for the prototype

## Routes
- `/` — Patients homepage
- `/providers` — Providers
- `/before-after` — Results gallery
- `/find-a-provider` — Provider finder prototype
- `/about-us` — About
- `/contact-us` — Contact

## Upgrade from V2
Keep the technical module folder named `premium_wave_website`.
Replace the old folder with this one, restart Odoo, and upgrade the module.

Example:

```bash
./odoo-bin -c /path/to/odoo.conf -d YOUR_DATABASE -u premium_wave_website --stop-after-init
```

Then start Odoo normally.

## Prototype note
The visual build currently uses Sofwave reference media supplied/downloaded for prototyping. Replace third-party branding/media with licensed customer assets before production if the customer does not own usage rights.

The V3 contact form demonstrates the finished UI and success state. It does not yet create a CRM lead. That backend connection is a good V4 step.


## V3.2
- Rebuilt the mobile navigation to a full-screen Sofwave-style menu.
- Added circular animated hamburger/close control.
- Added Patients / Providers audience switch inside the mobile menu.
- Added large editorial navigation rows, contact CTA and mobile social row.
- Locks page scrolling while the mobile menu is open and supports Escape to close.


## V3.5 header fix

Odoo 19 can re-apply its selected Website header template after a generic `website.layout` header replacement. V3.5 no longer competes with that template. It keeps the Odoo native header hidden and mounts the Premium Wave header independently before the page content, so changing/refreshing the Odoo header template cannot replace the custom desktop or mobile menu.
