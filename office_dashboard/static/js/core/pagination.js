'use strict';
/* Each record section owns its visible count; totals and exports keep full data. */
const sectionPagination = {size: 20, pages: new Map(), contexts: new Map()};
function sectionPaginationContext(group, signature) {
  const value = String(signature);
  if (sectionPagination.contexts.get(group) !== value) {
    for (const key of sectionPagination.pages.keys()) {
      if (key.startsWith(group + ':')) sectionPagination.pages.delete(key);
    }
    sectionPagination.contexts.set(group, value);
  }
}
function sectionPage(key, records, signature = '', label = 'Записи') {
  let page = sectionPagination.pages.get(key);
  if (!page || page.signature !== signature) {
    page = {signature, visible: sectionPagination.size, total: 0};
    sectionPagination.pages.set(key, page);
  }
  page.total = records.length;
  const shown = Math.min(page.visible, page.total), next = Math.min(sectionPagination.size, page.total - shown);
  const id = 'section-page-' + encodeURIComponent(key);
  const footer = page.total ? `<div class="section-pagination" id="${esc(id)}" tabindex="-1" aria-label="${esc(label)}">
    <span class="section-pagination-count muted" role="status">Показано ${shown} из ${page.total}</span>
    ${next ? `<button type="button" class="btn" data-page-more="${esc(key)}" aria-label="${esc(label)}: показать ещё ${next}">Показать ещё <span class="muted" aria-hidden="true">${next}</span></button>` : ''}
  </div>` : '';
  return {rows: records.slice(0, shown), footer};
}
function sectionPaginationClick(event, render, canChange = () => true) {
  const button = event.target.closest('[data-page-more]');
  if (!button) return false;
  if (!canChange()) return true;
  const key = button.dataset.pageMore, page = sectionPagination.pages.get(key);
  if (!page || page.visible >= page.total) return true;
  page.visible = Math.min(page.visible + sectionPagination.size, page.total);
  render(key);
  // Keep keyboard focus without jumping down past the newly revealed records.
  const footer = document.getElementById('section-page-' + encodeURIComponent(key));
  (footer?.querySelector('[data-page-more]') || footer)?.focus({preventScroll: true});
  return true;
}
