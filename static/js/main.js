/**
 * Eligald Industrial Chemicals – main.js
 * Handles: AOS init, header scroll, back-to-top, product search,
 *          newsletter toast, navbar active state.
 */

document.addEventListener('DOMContentLoaded', function () {

  /* ─── AOS (Animate on Scroll) ──────────────────────────────────────── */
  if (typeof AOS !== 'undefined') {
    AOS.init({
      duration: 600,
      easing: 'ease-out-cubic',
      once: true,
      offset: 60,
    });
  }

  /* ─── Sticky header shadow on scroll ──────────────────────────────── */
  const header = document.getElementById('main-header');
  const onScroll = () => {
    if (window.scrollY > 40) {
      header && header.classList.add('scrolled');
    } else {
      header && header.classList.remove('scrolled');
    }
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ─── Back to top ──────────────────────────────────────────────────── */
  const btt = document.getElementById('back-to-top');
  if (btt) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 350) {
        btt.classList.add('visible');
      } else {
        btt.classList.remove('visible');
      }
    }, { passive: true });

    btt.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  /* ─── Product search / filter ──────────────────────────────────────── */
  const searchInput = document.getElementById('product-search');
  const productGrid = document.getElementById('product-grid');
  const noResults   = document.getElementById('no-results');

  if (searchInput && productGrid) {
    searchInput.addEventListener('input', function () {
      const q = this.value.trim().toLowerCase();
      const cards = productGrid.querySelectorAll('.product-card-wrap');
      let visible = 0;

      cards.forEach(function (card) {
        const name = (card.dataset.name     || '').toLowerCase();
        const cat  = (card.dataset.category || '').toLowerCase();
        const desc = card.querySelector('.product-desc')
          ? card.querySelector('.product-desc').textContent.toLowerCase()
          : '';

        const match = !q || name.includes(q) || cat.includes(q) || desc.includes(q);
        card.style.display = match ? '' : 'none';
        if (match) visible++;
      });

      if (noResults) {
        noResults.classList.toggle('d-none', visible > 0);
      }
    });
  }

  /* ─── Newsletter form (footer) ─────────────────────────────────────── */
  const nlForm  = document.getElementById('newsletter-form');
  const nlToast = document.getElementById('newsletter-toast');
  if (nlForm && nlToast) {
    nlForm.addEventListener('submit', function (e) {
      e.preventDefault();
      const emailInput = this.querySelector('input[type="email"]');
      if (!emailInput || !emailInput.value.includes('@')) return;
      emailInput.value = '';
      nlToast.classList.remove('d-none');
      setTimeout(function () { nlToast.classList.add('d-none'); }, 4000);
    });
  }

  /* ─── Smooth scroll for anchor links (About page sections) ─────────── */
  document.querySelectorAll('a[href*="#"]').forEach(function (link) {
    link.addEventListener('click', function (e) {
      const href = this.getAttribute('href');
      // Only handle same-page anchors
      if (!href.startsWith('#') && !href.includes(window.location.pathname + '#')) return;
      const id = href.split('#')[1];
      if (!id) return;
      const target = document.getElementById(id);
      if (!target) return;
      e.preventDefault();
      const offset = 80; // header height
      const top = target.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });
    });
  });

  /* ─── Mobile: close navbar when a nav link is clicked ──────────────── */
  const navCollapse = document.getElementById('navbarMain');
  if (navCollapse) {
    navCollapse.querySelectorAll('.nav-link, .dropdown-item').forEach(function (item) {
      item.addEventListener('click', function () {
        if (window.innerWidth < 992) {
          const bsCollapse = bootstrap.Collapse.getInstance(navCollapse);
          if (bsCollapse) bsCollapse.hide();
        }
      });
    });
  }

});
