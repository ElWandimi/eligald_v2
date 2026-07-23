/* admin.js – Eligald Admin Panel */

document.addEventListener('DOMContentLoaded', function () {

  /* ── Sidebar toggle (mobile) ──────────────────────────────────── */
  const sidebar  = document.getElementById('adminSidebar');
  const toggle   = document.getElementById('sidebarToggle');
  let overlay    = document.querySelector('.sidebar-overlay');

  if (!overlay && sidebar) {
    overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);
  }

  function openSidebar()  { sidebar?.classList.add('open');    overlay?.classList.add('show'); }
  function closeSidebar() { sidebar?.classList.remove('open'); overlay?.classList.remove('show'); }

  toggle?.addEventListener('click', () =>
    sidebar?.classList.contains('open') ? closeSidebar() : openSidebar()
  );
  overlay?.addEventListener('click', closeSidebar);

  /* ── Notification polling ─────────────────────────────────────── */
  const notifDot        = document.getElementById('notif-dot');
  const sidebarBadge    = document.getElementById('sidebar-notif-count');
  const notifList       = document.getElementById('notif-list');

  function fetchNotifCount() {
    fetch('/admin/notifications/unread-count')
      .then(r => r.json())
      .then(data => {
        const n = data.count || 0;
        if (notifDot)     { notifDot.style.display     = n > 0 ? 'block' : 'none'; }
        if (sidebarBadge) { sidebarBadge.style.display = n > 0 ? 'inline' : 'none'; sidebarBadge.textContent = n; }
      })
      .catch(() => {});
  }

  function fetchNotifPreview() {
    if (!notifList) return;
    fetch('/admin/notifications/unread-count')
      .then(r => r.json())
      .then(() => {
        fetch('/admin/notifications/preview')
          .then(r => r.json())
          .then(data => {
            if (!data.notifications || data.notifications.length === 0) {
              notifList.innerHTML = '<div class="notif-empty">No new notifications.</div>';
              return;
            }
            notifList.innerHTML = data.notifications.map(n => `
              <a href="/admin/notifications/${n.id}/read"
                 class="notif-item ${n.is_read ? '' : 'unread'}">
                <div class="notif-dot-item" ${n.is_read ? 'style="opacity:0"' : ''}></div>
                <div>
                  <div>${escHtml(n.message)}</div>
                  <div class="notif-time">${n.created_at.substring(0,16).replace('T',' ')}</div>
                </div>
              </a>`).join('');
          })
          .catch(() => {
            notifList.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
          });
      })
      .catch(() => {});
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  fetchNotifCount();
  setInterval(fetchNotifCount, 30000);

  document.querySelector('.notif-dropdown .topbar-icon-btn')?.addEventListener('click', fetchNotifPreview);

  /* ── Auto-dismiss alerts ─────────────────────────────────────── */
  document.querySelectorAll('.admin-alert').forEach(el => {
    setTimeout(() => {
      el.style.transition = 'opacity .5s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 500);
    }, 4500);
  });

  /* ── Order form: dynamic line items ─────────────────────────── */
  const addRowBtn  = document.getElementById('add-line-item');
  const itemsTable = document.getElementById('line-items-body');

  function calcRowTotal(row) {
    const qty   = parseFloat(row.querySelector('[name="item_quantity[]"]')?.value)   || 0;
    const price = parseFloat(row.querySelector('[name="item_unit_price[]"]')?.value) || 0;
    const tot   = row.querySelector('.row-total');
    if (tot) tot.textContent = 'KES ' + (qty * price).toLocaleString('en-KE', {minimumFractionDigits:2});
  }

  function updateGrandTotal() {
    let grand = 0;
    document.querySelectorAll('.line-item-row').forEach(row => {
      const qty   = parseFloat(row.querySelector('[name="item_quantity[]"]')?.value)   || 0;
      const price = parseFloat(row.querySelector('[name="item_unit_price[]"]')?.value) || 0;
      grand += qty * price;
    });
    const gt = document.getElementById('grand-total');
    if (gt) gt.textContent = 'KES ' + grand.toLocaleString('en-KE', {minimumFractionDigits:2});
  }

  function attachRowEvents(row) {
    row.querySelectorAll('input, select').forEach(inp => {
      inp.addEventListener('input', () => { calcRowTotal(row); updateGrandTotal(); });
    });
    row.querySelector('.remove-row-btn')?.addEventListener('click', () => {
      row.remove(); updateGrandTotal();
    });

    // Auto-fill unit price from product dropdown
    const prodSel = row.querySelector('[name="item_product_id[]"]');
    const descInp = row.querySelector('[name="item_description[]"]');
    if (prodSel && descInp) {
      prodSel.addEventListener('change', function() {
        const opt = this.options[this.selectedIndex];
        if (opt.value && descInp.value === '') {
          descInp.value = opt.textContent.trim();
        }
      });
    }
  }

  if (addRowBtn && itemsTable) {
    // Attach to existing rows
    document.querySelectorAll('.line-item-row').forEach(attachRowEvents);

    addRowBtn.addEventListener('click', function() {
      const allRows = document.querySelectorAll('.line-item-row');
      const tpl     = allRows[allRows.length - 1]?.cloneNode(true);
      if (!tpl) return;
      tpl.querySelectorAll('input').forEach(i => { i.value = ''; });
      tpl.querySelector('select')?.selectedOptions && (tpl.querySelector('select').selectedIndex = 0);
      const tot = tpl.querySelector('.row-total');
      if (tot) tot.textContent = 'KES 0.00';
      itemsTable.appendChild(tpl);
      attachRowEvents(tpl);
    });
  }

  /* ── Password show/hide ──────────────────────────────────────── */
  document.querySelectorAll('.pw-toggle').forEach(btn => {
    btn.addEventListener('click', function() {
      const inp  = this.closest('.input-group')?.querySelector('input[type="password"],input[type="text"]');
      const icon = this.querySelector('i');
      if (!inp) return;
      if (inp.type === 'password') { inp.type = 'text';     icon?.classList.replace('fa-eye','fa-eye-slash'); }
      else                         { inp.type = 'password'; icon?.classList.replace('fa-eye-slash','fa-eye'); }
    });
  });

});
