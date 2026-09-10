/** @odoo-module **/

(function () {
    'use strict';

    function initPremiumWaveV2() {
        const page = document.querySelector('.pw2-page');
        if (!page) return;

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
            }, { threshold: 0.14, rootMargin: '0px 0px -40px 0px' });
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

        // Mobile navigation.
        const toggle = document.querySelector('.pw2-mobile-toggle');
        const menu = document.querySelector('.pw2-mobile-menu');
        if (toggle && menu) {
            toggle.addEventListener('click', () => {
                const opened = menu.classList.toggle('is-open');
                toggle.setAttribute('aria-expanded', opened ? 'true' : 'false');
            });
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

        // Before / after slider.
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

        // Current year.
        document.querySelectorAll('.pw2-current-year').forEach((el) => {
            el.textContent = String(new Date().getFullYear());
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPremiumWaveV2, { once: true });
    } else {
        initPremiumWaveV2();
    }
})();
