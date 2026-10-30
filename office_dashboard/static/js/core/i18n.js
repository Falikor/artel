'use strict';
/* Interface locale only: never translate task content, logs, config, or model instructions. */
var artelLanguage = (() => {
  try { return localStorage.getItem('artel-language') === 'en' ? 'en' : 'ru'; }
  catch { return 'ru'; }
})();
function tr(ru, en) { return artelLanguage === 'en' ? en : ru; }
function uiLocale() { return artelLanguage === 'en' ? 'en-US' : 'ru-RU'; }
const artelServerMessages = new Map();
function registerServerMessages(entries) {
  for (const [ru, en] of Object.entries(entries)) artelServerMessages.set(ru, en);
}
const artelServerMessagePatterns = [];
function registerServerMessagePatterns(patterns) {
  for (const rule of patterns) {
    if (!rule.match.source.startsWith('^') || !rule.match.source.endsWith('$') || rule.match.global || rule.match.sticky)
      throw new Error('Server message patterns must match a complete message');
    artelServerMessagePatterns.push(rule);
  }
}
function translateServerMessage(message) {
  if (artelLanguage !== 'en' || typeof message !== 'string') return message;
  if (artelServerMessages.has(message)) return artelServerMessages.get(message);
  for (const rule of artelServerMessagePatterns) {
    const match = rule.match.exec(message);
    if (match && match[0] === message) return rule.translate(...match.slice(1));
  }
  return message;
}
const languageEditedFields = new Map();
function languageFieldValue(field) {
  return field.type === 'checkbox' || field.type === 'radio' ? field.checked : field.value;
}
function languageEditableField(field) {
  return field?.matches?.('input, select, textarea') && field.closest('form') &&
    !field.closest('#promptForm') && !field.disabled && !field.readOnly &&
    !['hidden', 'search', 'submit', 'button'].includes(field.type) &&
    !['themeSelect', 'languageSelect', 'cityNameBuilding'].includes(field.id);
}
function markFormClean(element) {
  const form = element?.matches?.('form') ? element : element?.closest?.('form');
  if (!form) return;
  for (const field of languageEditedFields.keys()) {
    if (field.closest('form') === form) languageEditedFields.set(field, languageFieldValue(field));
  }
}
function languageFieldRetained(field) {
  if (field.isConnected) return true;
  // Workspace tabs retain real form nodes while their screen is not mounted.
  // Those drafts still need protection; cancelled or replaced forms do not.
  return typeof workspace !== 'undefined' && Object.values(workspace.cache || {}).some(
    entry => (entry.nodes || []).some(node => node === field || node.contains?.(field)));
}
function languageHasUnsavedChanges() {
  if (typeof promptEditor !== 'undefined' && typeof promptDirty === 'function' &&
      [...promptEditor.entries.values()].some(entry => promptDirty(entry))) return true;
  for (const [field, original] of languageEditedFields) {
    if (!languageFieldRetained(field)) { languageEditedFields.delete(field); continue; }
    if (languageFieldValue(field) !== original) return true;
  }
  return false;
}
function applyInterfaceLanguage() {
  document.documentElement.lang = artelLanguage;
  for (const element of document.querySelectorAll('[data-i18n-en]')) {
    if (artelLanguage === 'en' && /[А-Яа-яЁё]/.test(element.textContent))
      element.textContent = element.getAttribute('data-i18n-en');
  }
  for (const attribute of ['aria-label', 'title', 'placeholder', 'content']) {
    for (const element of document.querySelectorAll(`[data-i18n-${attribute}]`)) {
      if (artelLanguage === 'en') element.setAttribute(attribute, element.getAttribute(`data-i18n-${attribute}`));
    }
  }
  const select = document.getElementById('languageSelect');
  if (select) select.value = artelLanguage;
}
/* Set language before first paint. Static labels are annotated, never inferred from text. */
document.documentElement.lang = artelLanguage;
document.addEventListener('DOMContentLoaded', () => {
  applyInterfaceLanguage();
  document.addEventListener('focusin', event => {
    const field = event.target;
    if (languageEditableField(field) && !languageEditedFields.has(field))
      languageEditedFields.set(field, languageFieldValue(field));
  });
  for (const eventName of ['input', 'change']) document.addEventListener(eventName, event => {
    const field = event.target;
    if (languageEditableField(field) && !languageEditedFields.has(field)) {
      // Handles edits made without focus (autofill, assistive technology).
      const original = field.type === 'checkbox' || field.type === 'radio'
        ? field.defaultChecked : (field.tagName === 'SELECT'
          ? [...field.options].find(option => option.defaultSelected)?.value ?? field.options[0]?.value ?? ''
          : field.defaultValue);
      languageEditedFields.set(field, original);
    }
  });
  document.getElementById('languageSelect')?.addEventListener('change', event => {
    const next = event.target.value === 'en' ? 'en' : 'ru';
    if (next === artelLanguage) return;
    if (languageHasUnsavedChanges() && !window.confirm(tr(
      'При смене языка страница перезагрузится. Несохранённые изменения будут потеряны. Продолжить?',
      'Changing the language reloads this page. Unsaved changes will be lost. Continue?'))) {
      event.target.value = artelLanguage;
      return;
    }
    try { localStorage.setItem('artel-language', next); }
    catch {
      event.target.value = artelLanguage;
      window.alert(tr('Браузер не позволяет сохранить язык. Разрешите хранение данных для этого сайта.',
        'Your browser cannot save the language preference. Allow site storage and try again.'));
      return;
    }
    window.artelLanguageReloadApproved = true;
    window.location.reload();
  });
});
