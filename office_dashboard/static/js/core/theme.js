'use strict';
// Apply before styles paint; this preference belongs to this browser, not daemon config.
(() => {
  const key = 'artel-theme', allowed = ['system', 'light', 'dark'];
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { const saved = localStorage.getItem(key); if (allowed.includes(saved)) preference = saved; } catch {}
  function apply() {
    const theme = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    // Separate local assets honor an app preference different from the OS.
    const favicon = document.getElementById('themeFavicon');
    const href = `/static/favicon-${theme}.svg`;
    if (favicon && favicon.getAttribute('href') !== href) favicon.setAttribute('href', href);
    const select = document.getElementById('themeSelect');
    if (select) select.value = preference;
  }
  apply();
  media.addEventListener('change', () => { if (preference === 'system') apply(); });
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = allowed.includes(event.newValue) ? event.newValue : 'system'; apply(); }
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.getElementById('themeSelect')?.addEventListener('change', event => {
      preference = allowed.includes(event.target.value) ? event.target.value : 'system';
      try { localStorage.setItem(key, preference); } catch {}
      apply();
    });
  });
})();
