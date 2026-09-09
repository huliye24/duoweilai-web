/* Duoweilai client interactions — ported from the single-file v0.5 server.
   v0.6 changes: the explore category filter is gone (server-side now), and
   POSTs go through api(), which attaches the X-CSRF-Token header. */
(function () {
  const toastRoot = document.getElementById('toast-root');
  window.toast = function (msg, kind) {
    const t = document.createElement('div');
    t.className = 'toast ' + (kind || '');
    t.textContent = msg;
    toastRoot.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 250);
    }, 2200);
  };

  // Confirm dialog (replacement for window.confirm — looks better + non-blocking)
  window.confirmModal = function (title, msg, opts) {
    opts = opts || {};
    return new Promise(resolve => {
      const root = document.getElementById('confirm-root');
      const box = document.getElementById('confirm-box');
      box.innerHTML = '<h3></h3><p></p><div class="actions"><button data-act="cancel">Cancel</button><button data-act="ok" class="' + (opts.danger ? 'danger' : 'primary') + '">' + (opts.okLabel || 'Confirm') + '</button></div>';
      box.querySelector('h3').textContent = title;
      box.querySelector('p').textContent = msg;
      root.classList.add('open');
      function close(v) {
        root.classList.remove('open');
        box.innerHTML = '';
        resolve(v);
      }
      box.querySelector('[data-act=cancel]').onclick = () => close(false);
      box.querySelector('[data-act=ok]').onclick = () => close(true);
    });
  };

  // ---------- CSRF + JSON-aware POST helper ----------
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const CSRF_TOKEN = csrfMeta ? csrfMeta.getAttribute('content') : '';
  async function api(url, fields) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRF-Token': CSRF_TOKEN },
      body: fields || ''
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || j.ok === false) throw new Error(j.error || 'Request failed (' + r.status + ')');
    return j;
  }
  function enc(el) { return encodeURIComponent(el.value); }

  // ---------- Notifications bell: mark as read when clicked ----------
  const bell = document.querySelector('a[href="/notifications"]');
  if (bell) bell.addEventListener('click', () => {
    const badge = bell.querySelector('span');
    if (badge) badge.remove();
    fetch('/api/notifications/read', { method: 'GET' }).catch(() => {});
  });

  // ---------- Publish form: enable button + keyboard shortcut ----------
  const fi = document.getElementById('futureInput');
  const pb = document.getElementById('publishBtn');
  if (fi && pb) {
    fi.addEventListener('input', () => { pb.disabled = !fi.value.trim(); });
    fi.addEventListener('keydown', e => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        if (fi.value.trim()) fi.form.submit();
      }
    });
  }

  // ---------- Profile tabs ----------
  document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(x => x.style.display = 'none');
      t.classList.add('active');
      const pane = document.getElementById(t.dataset.tab);
      if (pane) pane.style.display = 'block';
    });
  });

  // ---------- Header scroll shadow ----------
  const hdr = document.getElementById('site-header');
  if (hdr) window.addEventListener('scroll', () => hdr.classList.toggle('scrolled', window.scrollY > 10));

  // ---------- Delegated handlers ----------
  document.body.addEventListener('click', async e => {
    // Copy link buttons
    const copy = e.target.closest('[data-copy]');
    if (copy) {
      const raw = copy.dataset.copy;
      const url = raw.startsWith('http') ? raw : location.origin + raw;
      try {
        await navigator.clipboard.writeText(url);
        toast('Link copied', 'ok');
      } catch (_) {
        toast('Copy failed', 'err');
      }
      return;
    }

    // Delete buttons (redirect for whole-page delete, AJAX for inline)
    const del = e.target.closest('[data-delete]');
    if (del) {
      e.preventDefault();
      const url = del.dataset.delete;
      const what = del.dataset.label || 'this';
      const ok = await confirmModal('Delete ' + what + '?', 'This cannot be undone.', { danger: true, okLabel: 'Delete' });
      if (!ok) return;
      try {
        const j = await api(url);
        // If the API returned a redirect target, navigate; otherwise remove from DOM.
        if (j.redirect) {
          location.href = j.redirect;
          return;
        }
        const row = del.closest('[data-row],.contrib-item,.comment,.item');
        if (row) { row.style.transition = 'opacity .2s ease'; row.style.opacity = '0'; setTimeout(() => row.remove(), 220); }
        toast('Deleted', 'ok');
      } catch (err) {
        toast(err.message || 'Delete failed', 'err');
      }
      return;
    }

    // Reply toggles
    const rep = e.target.closest('[data-reply-toggle]');
    if (rep) {
      const form = rep.closest('.comment').querySelector('.reply-form');
      if (form) {
        form.classList.toggle('open');
        const ta = form.querySelector('textarea');
        if (form.classList.contains('open') && ta) ta.focus();
      }
      return;
    }

    // Reply submit (cancel + post)
    if (e.target.matches('[data-reply-cancel]')) {
      const f = e.target.closest('.reply-form');
      if (f) f.classList.remove('open');
      return;
    }
    if (e.target.matches('[data-reply-post]')) {
      const f = e.target.closest('.reply-form');
      const ta = f.querySelector('textarea');
      const body = ta.value.trim();
      if (!body) { toast('Empty reply', 'err'); return; }
      const futureId = f.dataset.futureId;
      const parentId = f.dataset.parentId;
      try {
        await api('/api/comment',
          'future_id=' + encodeURIComponent(futureId)
          + '&parent_id=' + encodeURIComponent(parentId)
          + '&body=' + encodeURIComponent(body));
        toast('Reply posted', 'ok');
        setTimeout(() => location.reload(), 400);
      } catch (err) {
        toast(err.message || 'Reply failed', 'err');
      }
      return;
    }

    // ---------- v0.6: inline edit panels (seed / contribution / comment) ----------
    const edt = e.target.closest('[data-edit-toggle]');
    if (edt) {
      e.preventDefault();
      let box = null;
      if (edt.dataset.editToggle === 'seed') {
        box = document.getElementById('seedEditForm');
      } else {
        const host = edt.closest('.contrib-item,.comment');
        box = host ? host.querySelector('.edit-form') : null;
      }
      if (box) {
        box.classList.toggle('open');
        const first = box.querySelector('input,textarea');
        if (box.classList.contains('open') && first) first.focus();
      }
      return;
    }
    if (e.target.matches('[data-edit-cancel]')) {
      const box = e.target.closest('.edit-form');
      if (box) box.classList.remove('open');
      return;
    }
    if (e.target.matches('[data-edit-save]')) {
      const box = e.target.closest('.edit-form');
      const fields = Array.from(box.querySelectorAll('[name]'))
        .map(el => el.name + '=' + enc(el)).join('&');
      try {
        await api(e.target.dataset.editSave, fields);
        toast('Saved', 'ok');
        setTimeout(() => location.reload(), 350);
      } catch (err) {
        toast(err.message || 'Save failed', 'err');
      }
      return;
    }

    // ---------- v0.6: branch form (derive a new seed from this one) ----------
    const brt = e.target.closest('[data-branch-toggle]');
    if (brt) {
      const box = document.getElementById('branchForm');
      if (box) {
        box.classList.toggle('open');
        const ta = box.querySelector('textarea');
        if (box.classList.contains('open') && ta) ta.focus();
      }
      return;
    }
    if (e.target.matches('[data-branch-cancel]')) {
      const box = document.getElementById('branchForm');
      if (box) box.classList.remove('open');
      return;
    }
    if (e.target.matches('[data-branch-save]')) {
      const box = document.getElementById('branchForm');
      const title = box.querySelector('[name=title]').value.trim();
      if (!title) { toast('Give the branch a title', 'err'); return; }
      const parts = ['title=' + encodeURIComponent(title)];
      box.querySelectorAll('[name]').forEach(el => {
        if (el.name !== 'title') parts.push(el.name + '=' + enc(el));
      });
      parts.push('parent=' + encodeURIComponent(e.target.dataset.parent));
      try {
        const j = await api('/api/future', parts.join('&'));
        toast('Branch planted', 'ok');
        setTimeout(() => location.href = '/f/' + j.short, 350);
      } catch (err) {
        toast(err.message || 'Branch failed', 'err');
      }
      return;
    }
  });
})();
