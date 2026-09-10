/** @odoo-module **/

(function () {
    'use strict';

    function initPremiumWaveV3() {
        const page = document.querySelector('.pw2-page');

        // Reveal on scroll.
        const revealItems = document.querySelectorAll('.pw2-reveal');
        if ('IntersectionObserver' in window) {
            const observer = new IntersectionObserver((entries, obs) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-visible');
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.12, rootMargin: '0px 0px -35px 0px' });
            revealItems.forEach((el) => observer.observe(el));
        } else {
            revealItems.forEach((el) => el.classList.add('is-visible'));
        }

        // Header shadow while scrolling.
        const header = document.querySelector('.pw2-site-header');
        if (header) {
            const onScroll = () => header.classList.toggle('is-sticky', window.scrollY > 16);
            onScroll();
            window.addEventListener('scroll', onScroll, { passive: true });
        }

        // V3.2 mobile navigation: full-screen Sofwave-style overlay.
        const toggle = document.querySelector('.pw2-mobile-toggle');
        const menu = document.querySelector('.pw2-mobile-menu');
        if (toggle && menu) {
            const mobileHeader = document.querySelector('.pw2-site-header');
            const setMenuState = (opened) => {
                menu.classList.toggle('is-open', opened);
                toggle.classList.toggle('is-open', opened);
                if (mobileHeader) mobileHeader.classList.toggle('is-menu-open', opened);
                document.documentElement.classList.toggle('pw4-menu-open', opened);
                toggle.setAttribute('aria-expanded', opened ? 'true' : 'false');
                toggle.setAttribute('aria-label', opened ? 'Close menu' : 'Open menu');
                menu.setAttribute('aria-hidden', opened ? 'false' : 'true');
            };

            toggle.addEventListener('click', () => {
                setMenuState(!menu.classList.contains('is-open'));
            });

            menu.querySelectorAll('a').forEach((link) => {
                link.addEventListener('click', () => setMenuState(false));
            });

            document.addEventListener('keydown', (ev) => {
                if (ev.key === 'Escape' && menu.classList.contains('is-open')) {
                    setMenuState(false);
                    toggle.focus();
                }
            });

            window.addEventListener('resize', () => {
                if (window.innerWidth >= 992 && menu.classList.contains('is-open')) {
                    setMenuState(false);
                }
            }, { passive: true });
        }

        // Hero video pause/play.
        const video = document.querySelector('.pw2-hero-video');
        const videoToggle = document.querySelector('.pw2-video-toggle');
        if (video && videoToggle) {
            videoToggle.addEventListener('click', () => {
                if (video.paused) {
                    video.play().catch(() => {});
                    videoToggle.classList.remove('is-paused');
                    videoToggle.setAttribute('aria-label', 'Pause hero video');
                } else {
                    video.pause();
                    videoToggle.classList.add('is-paused');
                    videoToggle.setAttribute('aria-label', 'Play hero video');
                }
            });
        }

        // Before / after sliders.
        document.querySelectorAll('.pw2-before-after').forEach((box) => {
            const range = box.querySelector('.pw2-ba-range');
            if (!range) return;
            const update = () => box.style.setProperty('--pw2-ba-position', `${range.value}%`);
            range.addEventListener('input', update);
            update();
        });

        // Animated counters.
        const counters = document.querySelectorAll('[data-pw2-counter]');
        const animateCounter = (el) => {
            if (el.dataset.pw2Done === '1') return;
            el.dataset.pw2Done = '1';
            const target = Number(el.dataset.pw2Counter || 0);
            const suffix = el.dataset.pw2Suffix || '';
            const duration = 1100;
            const start = performance.now();
            const tick = (now) => {
                const progress = Math.min((now - start) / duration, 1);
                const eased = 1 - Math.pow(1 - progress, 3);
                el.textContent = `${Math.round(target * eased)}${suffix}`;
                if (progress < 1) requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        };
        if ('IntersectionObserver' in window) {
            const counterObserver = new IntersectionObserver((entries, obs) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        animateCounter(entry.target);
                        obs.unobserve(entry.target);
                    }
                });
            }, { threshold: .45 });
            counters.forEach((el) => counterObserver.observe(el));
        } else {
            counters.forEach(animateCounter);
        }

        // Treatment area explorer.
        const setArea = (area) => {
            document.querySelectorAll('[data-pw3-area]').forEach((el) => {
                el.classList.toggle('is-active', el.dataset.pw3Area === area);
            });
            document.querySelectorAll('[data-pw3-panel]').forEach((el) => {
                el.classList.toggle('is-active', el.dataset.pw3Panel === area);
            });
        };
        document.querySelectorAll('[data-pw3-area]').forEach((el) => {
            el.addEventListener('click', () => setArea(el.dataset.pw3Area));
        });

        // Testimonial carousel.
        const quotes = Array.from(document.querySelectorAll('.pw3-quote'));
        let quoteIndex = Math.max(0, quotes.findIndex((q) => q.classList.contains('is-active')));
        const showQuote = (index) => {
            if (!quotes.length) return;
            quoteIndex = (index + quotes.length) % quotes.length;
            quotes.forEach((q, i) => q.classList.toggle('is-active', i === quoteIndex));
        };
        document.querySelectorAll('[data-pw3-quote]').forEach((button) => {
            button.addEventListener('click', () => showQuote(quoteIndex + (button.dataset.pw3Quote === 'next' ? 1 : -1)));
        });

        // Before/after category filter.
        const filterButtons = document.querySelectorAll('[data-pw3-filter]');
        const resultItems = document.querySelectorAll('.pw3-result-item');
        filterButtons.forEach((button) => {
            button.addEventListener('click', () => {
                const filter = button.dataset.pw3Filter;
                filterButtons.forEach((b) => b.classList.toggle('is-active', b === button));
                resultItems.forEach((item) => {
                    item.classList.toggle('is-hidden', filter !== 'all' && item.dataset.pw3Category !== filter);
                });
            });
        });

        // Provider finder prototype search.
        const providerSearch = document.getElementById('pw3-provider-search');
        const providerSearchButton = document.getElementById('pw3-provider-search-button');
        const providerRows = Array.from(document.querySelectorAll('.pw3-clinic-row'));
        const providerCount = document.getElementById('pw3-provider-count');
        const providerEmpty = document.getElementById('pw3-provider-empty');
        const runProviderSearch = () => {
            if (!providerSearch) return;
            const query = providerSearch.value.toLowerCase().trim();
            let visible = 0;
            providerRows.forEach((row) => {
                const match = !query || (row.dataset.search || row.textContent || '').toLowerCase().includes(query);
                row.classList.toggle('is-hidden', !match);
                if (match) visible += 1;
            });
            if (providerCount) providerCount.textContent = String(visible);
            if (providerEmpty) providerEmpty.classList.toggle('is-visible', visible === 0);
        };
        if (providerSearch) {
            providerSearch.addEventListener('input', runProviderSearch);
            providerSearch.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter') { ev.preventDefault(); runProviderSearch(); }
            });
        }
        if (providerSearchButton) providerSearchButton.addEventListener('click', runProviderSearch);

        // Contact patient/provider switch.
        const contactForm = document.querySelector('.pw3-contact-form');
        const audienceInput = document.getElementById('pw3-audience-value');
        const contactButtons = document.querySelectorAll('[data-pw3-contact]');
        const applyAudience = (audience) => {
            if (contactForm) contactForm.classList.toggle('is-provider', audience === 'provider');
            if (audienceInput) audienceInput.value = audience;
            contactButtons.forEach((button) => button.classList.toggle('is-active', button.dataset.pw3Contact === audience));
        };
        contactButtons.forEach((button) => button.addEventListener('click', () => applyAudience(button.dataset.pw3Contact)));
        if (audienceInput) applyAudience(audienceInput.value || 'patient');

        // FAQ accordion.
        document.querySelectorAll('.pw3-accordion article > button').forEach((button) => {
            button.addEventListener('click', () => {
                const article = button.closest('article');
                if (article) article.classList.toggle('is-open');
            });
        });

        // Floating contact control.
        const chatButton = document.querySelector('.pw3-chat-button');
        const chatPanel = document.querySelector('.pw3-chat-panel');
        if (chatButton && chatPanel) {
            chatButton.addEventListener('click', () => {
                const open = chatPanel.classList.toggle('is-open');
                chatPanel.setAttribute('aria-hidden', open ? 'false' : 'true');
                chatButton.setAttribute('aria-expanded', open ? 'true' : 'false');
            });
        }

        // Current year.
        document.querySelectorAll('.pw2-current-year').forEach((el) => {
            el.textContent = String(new Date().getFullYear());
        });

        // Keep variable used to make intent explicit on pages where only global controls exist.
        void page;
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPremiumWaveV3, { once: true });
    } else {
        initPremiumWaveV3();
    }
})();
