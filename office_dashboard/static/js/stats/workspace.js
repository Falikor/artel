'use strict';
/* Dedicated analytics, retrospective and memory screens. All server text is escaped. */
const workspace = {view: 'office', timer: null, serial: 0, memory: null, data: null, cache: {}, busy: false};
const workspaceViews = ['analytics', 'memory', 'retro', 'requirements'];
const workspaceFilterIds = ['workspaceDays', 'workspaceOffice', 'workspaceDaemon', 'workspaceSearch', 'memoryFilter'];
function workspaceEditing() { return !!document.querySelector('#workspaceBody form'); }
function workspaceEditorState() {
  const editing = workspaceEditing();
  if (editing) $('workspaceBody').setAttribute('aria-busy', 'false');
  workspaceFilterIds.concat('workspaceRefresh').forEach(id => { $(id).disabled = editing; });
  $('workspaceBody').querySelectorAll('[data-page-more], [data-new-requirements], [data-again-requirements], [data-cancel-requirements], [data-memory-action=approve], [data-memory-action=retry], [data-memory-action=reject]').forEach(b=>{b.disabled=editing;});
  if (editing) $('workspaceStatus').textContent = tr('Изменения ещё не сохранены. Обновление и фильтры приостановлены до сохранения или отмены.', 'Changes are not saved yet. Refresh and filters are paused until you save or cancel.');
}
function workspaceEmpty(title, hint) {
  return `<div class="workspace-empty"><strong>${esc(title)}</strong><p>${esc(hint)}</p></div>`;
}
function workspaceRender(html) {
  const open = new Set([...$('workspaceBody').querySelectorAll('details[open][data-detail]')].map(d => d.dataset.detail));
  $('workspaceBody').innerHTML = html;
  $('workspaceBody').querySelectorAll('details[data-detail]').forEach(d => { d.open = open.has(d.dataset.detail); });
  enhanceDataTables($('workspaceBody'));
  workspaceEditorState();
}
function enhanceDataTables(root) {
  root.querySelectorAll('.table-wrap').forEach(wrap => {
    wrap.tabIndex = 0; wrap.setAttribute('role', 'region');
    wrap.querySelector('table')?.setAttribute('role', 'table');
    wrap.setAttribute('aria-label', tr('Таблица данных. При необходимости прокрутите по горизонтали.', 'Data table. Scroll horizontally if needed.'));
    const headers = [...wrap.querySelectorAll('thead th')];
    headers.forEach(h => h.setAttribute('scope', 'col'));
    wrap.querySelectorAll('tbody tr').forEach(row => [...row.children].forEach((cell, i) => {
      cell.dataset.label = headers[i]?.textContent.trim() || '';
    }));
  });
}
async function workspaceJson(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error(tr('Сервер вернул неожиданный ответ. Повторите попытку.', 'The server returned an unexpected response. Please try again.')); }
  if (!response.ok || data.error) throw new Error(translateServerMessage(data.error || data.reason || tr('Сервер недоступен (HTTP ', 'Server unavailable (HTTP ') + response.status + ')'));
  return data;
}
function daemonOptionName(d) {
  const name = displayName(d), parts = [name];
  if (d.project && d.project !== name) parts.push(d.project);
  if (d.id && d.id !== name) parts.push(d.id);
  return parts.join(' · ');
}
const memoryLabels = {candidate: tr('Кандидат', 'Candidate'), confirmed: tr('Подтверждено', 'Confirmed'), rejected: tr('Отклонено', 'Rejected')};
function memorySourceLabel(source) {
  const legacyKeys = {'генерация':'generation', 'ревью':'review', 'доработка':'rework', 'исследование':'explore', 'ретроспектива':'retro'};
  const labels = {generation:tr('генерация', 'Implementation'), review:tr('ревью', 'Review'), rework:tr('доработка', 'Rework'), explore:tr('исследование', 'Exploration'), retro:tr('ретроспектива', 'Retrospective'), legacy:tr('Прежние заметки', 'Legacy notes'), pr_review:tr('Замечания к PR', 'PR feedback')};
  const key = Object.prototype.hasOwnProperty.call(legacyKeys, source) ? legacyKeys[source] : source;
  return Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : source || '—';
}
function workspaceParams() {
  return new URLSearchParams({days: $('workspaceDays').value, office: $('workspaceOffice').value, id: $('workspaceDaemon').value});
}
function workspacePaginationKey() {
  const key = JSON.stringify(workspaceFilterIds.map(id => $(id).value.trim().toLowerCase()));
  sectionPaginationContext('workspace-' + workspace.view, key);
  return key;
}
function redrawWorkspace() {
  if (workspace.view === 'memory') drawMemory();
  else if (workspace.view === 'analytics') drawAnalytics(workspace.data);
  else if (workspace.view === 'retro') drawRetrospective(workspace.data);
  else if (workspace.view === 'requirements') drawRequirements(workspace.data);
}
function workspaceSelect(id, rows, label) {
  const el = $(id), selected = el.value;
  el.innerHTML = '<option value="">' + label + '</option>' + rows.map(r => `<option value="${esc(r.id)}">${esc(r.name || r.id)}</option>`).join('');
  if (rows.some(r => r.id === selected)) el.value = selected;
}
async function showWorkspace(view) {
  const previous = workspace.view;
  if (previous !== view && workspaceViews.includes(previous)) {
    workspace.cache[previous] = {nodes: [...$('workspaceBody').childNodes],
      filters: Object.fromEntries(workspaceFilterIds.map(id => [id, $(id).value])), data: workspace.data};
  }
  workspace.view = view;
  workspace.serial++;
  clearInterval(workspace.timer);
  $('workspace').hidden = !workspaceViews.includes(view);
  if ($('workspace').hidden) return;
  const names = {requirements: [tr('Переделки по новой постановке', 'Requirements rework'), tr('Отдельная очередь запросов. Демон начинает переделку после текущей работы. Ошибки не запускают автоматический повтор.', 'A separate request queue. The daemon starts rework after its current job. Failures do not trigger automatic retries.')],
    analytics: [tr('Аналитика работы', 'Work analytics'), tr('Сколько времени и попыток требуют задачи. Период определяется по последнему завершению задачи.', 'Time and attempts per task. The period follows each task’s latest completion.')],
    memory: [tr('Память демонов', 'Daemon memory'), tr('Проверенные знания и кандидаты в уроки. Автоматическая проверка оставляет вам только спорные решения.', 'Verified knowledge and lesson candidates. Automatic checks leave disputed decisions for you.')],
    retro: [tr('Ретроспектива', 'Retrospective'), tr('Что произошло со сданными задачами: слияния, правки и доработки. Исходы определяются по истории Git.', 'What happened to delivered work: merges, edits, and follow-ups. Outcomes are determined from Git history.')]};
  $('workspaceTitle').textContent = names[view][0]; $('workspaceHint').textContent = names[view][1];
  $('workspaceDays').hidden = view === 'memory';
  $('workspaceSearch').hidden = view === 'analytics';
  $('workspaceSearch').placeholder = view === 'memory' ? tr('Найти урок или задачу', 'Find a lesson or task') : view === 'retro' ? tr('Найти задачу, ветку или демона', 'Find a task, branch, or daemon') : tr('Найти задачу или постановку', 'Find a task or requirement');
  $('memoryFilter').hidden = view !== 'memory';
  const cached = workspace.cache[view];
  if (previous !== view) {
    $('workspaceBody').replaceChildren(...(cached?.nodes || []));
    workspace.data = cached?.data || null;
    workspaceFilterIds.forEach(id => { $(id).value = cached?.filters[id] ?? (id === 'workspaceDays' ? '30' : ''); });
  }
  workspaceEditorState();
  if (workspaceEditing()) {
    workspace.timer = setInterval(()=>{if (!document.hidden && !workspaceEditing()) loadWorkspace();},30000);
    return;
  }
  if (!$('workspaceBody').childNodes.length) $('workspaceBody').innerHTML = tr('<div class="workspace-loading" aria-label="Загрузка данных"><span></span><span></span><span></span></div>', '<div class="workspace-loading" aria-label="Loading data"><span></span><span></span><span></span></div>');
  $('workspaceStatus').textContent = tr('Загрузка данных…', 'Loading data…');
  try {
    const state = await workspaceJson('/api/state');
    if (workspace.view !== view) return;
    workspaceSelect('workspaceOffice', (state.offices || []).map(x => ({id:x.id, name:x.title})), tr('Все офисы', 'All offices'));
    workspaceSelect('workspaceDaemon', (state.daemons || []).map(d => ({id:d.id, name:daemonOptionName(d)})), tr('Все демоны', 'All daemons'));
    await loadWorkspace();
  } catch (e) {
    if (workspace.view !== view) return;
    $('workspaceStatus').textContent = tr('Не удалось загрузить данные: ', 'Could not load data: ') + translateServerMessage(e.message);
    if (!workspace.data) workspaceRender(workspaceEmpty(tr('Данные временно недоступны', 'Data is temporarily unavailable'), tr('Проверьте соединение с сервером и нажмите «Обновить».', 'Check the server connection and select Refresh.')));
  }
  if (workspace.view === view) workspace.timer = setInterval(() => { if (!document.hidden && !workspaceEditing()) loadWorkspace(); }, 30000);
}
function metric(label, value, note='') {
  return `<div class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${esc(String(value ?? '—'))}</div><div class="kpi-sub">${esc(note)}</div></div>`;
}
function minutes(n) { return n == null ? '—' : (n / 60).toLocaleString(uiLocale(), {maximumFractionDigits:1}) + tr(' мин', ' min'); }
function workspaceTable(head, rows) {
  return `<div class="table-wrap"><table class="workspace-table"><thead><tr>${head.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}
async function loadWorkspace(force=false) {
  if (workspaceEditing() && force !== true) { workspaceEditorState(); return; }
  const serial = ++workspace.serial, view = workspace.view;
  if (!workspaceViews.includes(view)) return;
  $('workspaceStatus').textContent = tr('Обновление…', 'Refreshing…');
  $('workspaceBody').setAttribute('aria-busy', 'true');
  const endpoint = {analytics: 'insights', memory: 'memory', retro: 'retrospective', requirements: 'requirements'}[view];
  try {
    const data = await workspaceJson('/api/' + endpoint + '?' + workspaceParams());
    if (serial !== workspace.serial || (workspaceEditing() && force !== true)) return false;
    workspace.data = data;
    if (view === 'requirements') drawRequirements(data);
    if (view === 'analytics') drawAnalytics(data);
    if (view === 'retro') drawRetrospective(data);
    if (view === 'memory') { workspace.memory = data; drawMemory(); }
    enhanceDataTables($('workspaceBody'));
    workspaceEditorState();
    if (!workspaceEditing()) $('workspaceStatus').textContent = tr('Обновлено ', 'Updated ') + new Date().toLocaleTimeString(uiLocale(), {hour:'2-digit', minute:'2-digit'});
    return true;
  } catch (e) {
    if (serial !== workspace.serial) return;
    $('workspaceStatus').textContent = tr('Данные не обновлены: ', 'Data was not refreshed: ') + translateServerMessage(e.message);
    if (!workspace.data) workspaceRender(workspaceEmpty(tr('Не удалось загрузить раздел', 'Could not load this section'), tr('Проверьте соединение и нажмите «Обновить».', 'Check your connection and select Refresh.')));
    return false;
  } finally { if (serial === workspace.serial) $('workspaceBody').setAttribute('aria-busy', 'false'); }
}
function drawAnalytics(data) {
  const t = data.totals;
  const page = sectionPage('workspace-analytics:groups', data.groups, workspacePaginationKey(), tr('Аналитика по демонам и сервисам', 'Analytics by daemon and service'));
  if (!t.tasks) { workspaceRender(workspaceEmpty(tr('За этот период ещё нет завершённых попыток', 'No completed attempts in this period yet'), tr('Выберите другой период или офис. Здесь появятся время работы, расход токенов и повторные попытки.', 'Choose another period or office. Work time, token usage, and retries will appear here.'))); return; }
  const money = t.cost == null ? '—' : t.cost.toLocaleString(uiLocale(), {maximumFractionDigits:2}) + ' ' + t.currency;
  workspaceRender(`<div class="kpis">${metric(tr('Задач', 'Tasks'), t.tasks, `${t.completed}${tr(" завершены успешно или с замечаниями", " completed successfully or with notes")}`)}${metric(tr('Попыток', 'Attempts'), t.attempts, `${t.failed_attempts}${tr(" неудачных", " failed")}`)}${metric(tr('С первой попытки', 'First attempt'), t.first_pass, `${tr("из ", "of ")}${t.completed}${tr(" завершённых", " completed")}`)}${metric(tr('Медиана времени', 'Median time'), minutes(t.median_seconds))}${metric(tr('90-й перцентиль', '90th percentile'), minutes(t.p90_seconds), tr('90% задач заняли не больше этого времени', '90% of tasks took no longer than this'))}${metric(tr('Токены', 'Tokens'), t.tokens.toLocaleString(uiLocale()), `${tr("известны для ", "available for ")}${t.token_coverage}${tr(" из ", " of ")}${t.attempts}${tr(" попыток", " attempts")}`)}${metric(tr('Оценка стоимости', 'Estimated cost'), money, `${tr("учтено задач: ", "tasks counted: ")}${t.cost_coverage}${tr(" из ", " of ")}${t.tasks}${tr("; цены задаются в Статистике", "; set prices in Statistics")}`)}</div>` +
    workspaceTable([tr('Демон / сервис', 'Daemon / service'), tr('Задач', 'Tasks'), tr('Попыток', 'Attempts'), tr('Неудачных попыток', 'Failed attempts'), tr('Медиана', 'Median'), 'P90', tr('Токены', 'Tokens')], page.rows.map(g => `<tr>${[demonName(g.id) + (g.service ? ' / ' + g.service : ''), g.tasks, g.attempts, g.failed_attempts, minutes(g.median_seconds), minutes(g.p90_seconds), g.tokens.toLocaleString(uiLocale())].map(v => `<td>${esc(String(v))}</td>`).join('')}</tr>`)) + page.footer);
}
function drawRetrospective(data) {
  const t = data.summary.totals, labels = {as_is:tr('Слито без правок', 'Merged unchanged'), changed:tr('Слито с правками', 'Merged with changes'), dropped:tr('Удалено без слияния', 'Deleted without merging'), open:tr('Ещё открыто', 'Still open'), waiting:tr('Ожидает проверки', 'Awaiting check'), unknown:tr('Исход неизвестен', 'Outcome unknown')};
  const query = $('workspaceSearch').value.trim().toLowerCase();
  const rows = data.rows.filter(r => JSON.stringify([r.issue, r.id, demonName(r.id), r.branch, labels[r.category]]).toLowerCase().includes(query));
  const page = sectionPage('workspace-retro:tasks', rows, workspacePaginationKey(), tr('Ретроспектива', 'Retrospective'));
  workspaceRender(`<div class="kpis">${Object.entries(labels).map(([k,l]) => metric(l,t[k])).join('')}</div>` + (rows.length ? workspaceTable([tr('Задача / демон', 'Task / daemon'), tr('Исход', 'Outcome'), tr('Правки людей', 'Human edits'), tr('Доработки', 'Follow-ups'), tr('Последняя проверка', 'Last check'), tr('Подробности', 'Details')], page.rows.map(r => `<tr><td><strong>${esc(r.issue)}</strong><br>${esc(r.id)} ${esc(r.service || '')}</td><td>${esc(labels[r.category] || r.category)}</td><td>${esc(String(r.human_commits))}${tr(" коммитов", " commits")}<br>≈ ${esc(String(r.human_lines))}${tr(" строк", " lines")}</td><td>${esc(String(r.followups))}</td><td>${r.checked_at ? esc(new Date(r.checked_at * 1000).toLocaleString(uiLocale())) : tr('Ещё не проверена', 'Not checked yet')}</td><td><details data-detail="${esc(r.id + ":" + r.issue)}"><summary>${tr("Ветка и сдача", "Branch and delivery")}</summary><p>${esc(r.branch || '—')}</p><p>${tr("База: ", "Base: ")}${esc(r.base || '—')}</p><p>${tr("Коммит: ", "Commit: ")}<code>${esc(r.head || '—')}</code></p><p>${tr("Сдана: ", "Delivered: ")}${esc(new Date(r.delivered_at * 1000).toLocaleString(uiLocale()))}</p><p>Jira: ${esc(r.jira_status || tr('неизвестно', 'unknown'))}</p></details></td></tr>`)) + page.footer : workspaceEmpty(tr('Сданных задач не найдено', 'No delivered tasks found'), tr('Измените период, офис или поисковый запрос. Ретроспектива появится после сдачи и проверки задачи.', 'Change the period, office, or search. A retrospective appears after work is delivered and checked.'))));
}
function drawMemory() {
  const data = workspace.memory;
  if (!data) return;
  if (!data.available) { workspaceRender(workspaceEmpty(tr('Память в этом режиме недоступна', 'Memory is unavailable in this mode'), tr('Откройте основной дашборд рядом с конфигурациями демонов. Демо показывает интерфейс без доступа к рабочим знаниям.', 'Open the main dashboard alongside the daemon configs. The demo shows the interface without access to working knowledge.'))); return; }
  const filter = $('memoryFilter').value, query = $('workspaceSearch').value.trim().toLowerCase();
  const pageKey = workspacePaginationKey();
  let count = 0, disputed = 0, confirmed = 0;
  const emptySources = [];
  const cards = data.sources.map(source => {
    const entries = source.entries.filter(e => {
      count++; if (e.needs_review) disputed++; if (e.status === 'confirmed') confirmed++;
      return (!filter || (filter === 'disputed' ? e.needs_review : e.status === filter)) && JSON.stringify(e).toLowerCase().includes(query);
    });
    const page = sectionPage('workspace-memory:source:' + source.key, entries, pageKey, tr('Уроки: ', 'Lessons: ') + (source.name || source.id));
    if (!source.entries.length && !source.error && !source.legacy) { emptySources.push(source); return ''; }
    if (!entries.length && !source.error && !source.legacy && (query || filter)) return '';
    return `<section class="memory-source"><div class="memory-source-head"><h3>${esc(source.name || source.id)}</h3><span class="muted">${esc(source.service || source.id)}</span><span class="memory-count">${entries.length}${tr(" записей", " entries")}</span></div>${source.error ? `<p>${esc(translateServerMessage(source.error))}</p>` : ''}${source.legacy ? tr('<p>Есть прежние заметки: демон импортирует их при следующем обращении к памяти.</p>', '<p>Legacy notes exist: the daemon will import them when it next accesses memory.</p>') : ''}${page.rows.map(e => `<article class="memory-entry"><div><span class="tag">${esc(memoryLabels[e.status] || e.status)}</span> ${e.needs_review ? tr('<strong class="needs-review">Нужно ваше решение</strong>', '<strong class="needs-review">Your decision is needed</strong>') : ''}</div><h4>${esc(e.text)}</h4><p class="muted">${tr("Задача: ", "Task: ")}${esc(e.issue || '—')}${tr(" · Источник: ", " · Source: ")}${esc(memorySourceLabel(e.source))}${tr(" · Наблюдений: ", " · Observations: ")}${esc(String(e.observations || 1))}</p><p>${tr("Область: ", "Scope: ")}${esc((e.scope || []).join(', ') || tr('общая', 'general'))}</p><details data-detail="${esc(source.key + ":" + e.id)}"><summary>${tr("Основание и проверка", "Evidence and verification")}</summary><p>${esc(e.evidence || tr('Основание ещё не записано', 'No evidence recorded yet'))}</p><pre>${esc(JSON.stringify(e.verification || {}, null, 2))}</pre></details>${data.control ? `<div class="memory-actions" data-source="${esc(source.key)}" data-entry="${esc(e.id)}">${e.status === 'candidate' ? tr('<button class="btn" data-memory-action="retry">Проверить повторно</button>', '<button class="btn" data-memory-action="retry">Check again</button>') : ''}${e.status !== 'confirmed' ? tr('<button class="btn" data-memory-action="approve">Подтвердить с основанием</button>', '<button class="btn" data-memory-action="approve">Confirm with evidence</button>') : ''}${e.status !== 'rejected' ? tr('<button class="btn" data-memory-action="reject">Отклонить</button>', '<button class="btn" data-memory-action="reject">Reject</button>') : ''}</div>` : ''}</article>`).join('') || tr('<p class="muted">Записей с такими фильтрами нет.</p>', '<p class="muted">No entries match these filters.</p>')}${page.footer}</section>`;
  }).join('');
  const emptyPage = sectionPage('workspace-memory:empty-sources', emptySources, pageKey, tr('Демоны без записей', 'Daemons without entries'));
  const emptyList = emptySources.length ? `<details class="empty-sources" data-detail="empty-sources"><summary>${tr("Демоны без записей · ", "Daemons without entries · ")}${emptySources.length}</summary><p class="muted">${tr("Память появится после работы над задачами и проверки предложенных уроков.", "Memory appears after task work and verification of proposed lessons.")}</p><ul>${emptyPage.rows.map(source=>`<li><strong>${esc(source.name || source.id)}</strong><span>${esc([source.service,source.id].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>${emptyPage.footer}</details>` : '';
  workspaceRender(`<div class="kpis">${metric(tr('Записей', 'Entries'),count)}${metric(tr('Подтверждено', 'Confirmed'),confirmed)}${metric(tr('Спорных', 'Disputed'),disputed)}</div>` + (cards || workspaceEmpty(query || filter ? tr('Подходящих уроков не найдено', 'No matching lessons found') : tr('Уроков пока нет', 'No lessons yet'), query || filter ? tr('Измените статус, поисковый запрос или фильтры.', 'Change the status, search, or filters.') : tr('После работы над задачами демоны предложат знания и проверят их по коду и тестам. Спорные записи появятся здесь.', 'After working on tasks, daemons propose knowledge and check it against code and tests. Disputed entries appear here.'))) + emptyList);
}
async function memoryAction(source, entry, action, evidence='', scope=[]) {
  const response = await fetch('/api/memory', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source, entry, action, evidence, scope})});
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const result = await response.json();
  if (!result.ok) throw new Error(translateServerMessage(result.error || result.reason || tr('Решение не сохранено', 'Decision was not saved')));
  delete workspace.cache.memory;
  if (workspace.view === 'memory') {
    // The POST already succeeded. Close the editor before the optional refresh,
    // so a failed GET cannot leave a saved lesson locked in a disabled form.
    $('workspaceBody').querySelectorAll('[data-source][data-entry]').forEach(container => {
      if (container.dataset.source === source && container.dataset.entry === entry) { markFormClean(container); container.textContent = tr('Решение сохранено.', 'Decision saved.'); }
    });
    workspaceEditorState();
    const refreshed = await loadWorkspace(true);
    $('workspaceStatus').textContent = refreshed ? tr('Решение сохранено.', 'Decision saved.') : tr('Решение сохранено. ', 'Decision saved. ') + $('workspaceStatus').textContent + tr(' Нажмите «Обновить», чтобы получить актуальные записи.', ' Select Refresh to get current entries.');
  }
}
$('workspaceBody').addEventListener('click', async event => {
  if (sectionPaginationClick(event, redrawWorkspace, () => !workspaceEditing())) return;
  const button = event.target.closest('[data-memory-action]'); if (!button) return;
  const container = button.closest('[data-source]'), {source,entry} = container.dataset, action = button.dataset.memoryAction;
  if (action === 'approve') {
    container.innerHTML = tr('<form class="memory-approval"><label>Основание решения<textarea name="evidence" required maxlength="1000" placeholder="Что проверено: код, тесты, принятое решение"></textarea></label><label>Области применения через запятую<input name="scope" maxlength="1000"></label><div class="form-actions"><button class="btn primary">Подтвердить урок</button><button class="btn" type="button" data-memory-action="cancel">Отмена</button></div><p class="form-status" role="status"></p></form>', '<form class="memory-approval"><label>Decision evidence<textarea name="evidence" required maxlength="1000" placeholder="What was checked: code, tests, or an agreed decision"></textarea></label><label>Scopes, separated by commas<input name="scope" maxlength="1000"></label><div class="form-actions"><button class="btn primary">Confirm lesson</button><button class="btn" type="button" data-memory-action="cancel">Cancel</button></div><p class="form-status" role="status"></p></form>');
    const lesson = workspace.memory?.sources.find(item => item.key === source)?.entries.find(item => item.id === entry);
    container.querySelector('[name=scope]').value = (lesson?.scope || []).join(', ');
    container.querySelector('textarea').focus(); workspaceEditorState(); return;
  }
  if (action === 'cancel') { markFormClean(container); drawMemory(); workspaceEditorState(); $('workspaceStatus').textContent = tr('Изменение урока отменено.', 'Lesson changes cancelled.'); return; }
  if (action === 'reject') {
    container.innerHTML = tr('<form class="memory-rejection"><p>Отклонить этот урок? Демон перестанет использовать его как знание. Запись останется в истории.</p><div class="form-actions"><button class="btn" type="submit">Отклонить урок</button><button class="btn" type="button" data-memory-action="cancel">Отмена</button></div><p role="status"></p></form>', '<form class="memory-rejection"><p>Reject this lesson? The daemon will stop using it as knowledge. The entry stays in the history.</p><div class="form-actions"><button class="btn" type="submit">Reject lesson</button><button class="btn" type="button" data-memory-action="cancel">Cancel</button></div><p role="status"></p></form>');
    workspaceEditorState(); container.querySelector('button').focus(); return;
  }
  button.disabled = true;
  try { await memoryAction(source,entry,action); } catch(e) { $('workspaceStatus').textContent=translateServerMessage(e.message); button.disabled=false; }
});
$('workspaceBody').addEventListener('submit', async event => {
  if (!event.target.matches('.memory-approval, .memory-rejection')) return;
  const form=event.target, container=form.closest('[data-source]');
  if (!container) return; // Other workspace forms share the layout class, not the memory action.
  event.preventDefault();
  form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try { await memoryAction(container.dataset.source, container.dataset.entry, form.matches('.memory-rejection') ? 'reject' : 'approve', form.elements.evidence?.value || '', (form.elements.scope?.value || '').split(',').map(x=>x.trim()).filter(Boolean)); }
  catch(e) { form.querySelector('[role=status]').textContent=translateServerMessage(e.message); form.querySelectorAll('button').forEach(b=>b.disabled=false); }
});
['workspaceDays','workspaceOffice','workspaceDaemon'].forEach(id=>$(id).addEventListener('change',()=>loadWorkspace()));
$('memoryFilter').addEventListener('change',()=>{ if (!workspaceEditing()) drawMemory(); });
let workspaceSearchTimer;
$('workspaceSearch').addEventListener('input',()=>{clearTimeout(workspaceSearchTimer);workspaceSearchTimer=setTimeout(()=>{ if (workspaceEditing()) return; if (workspace.view === 'memory') drawMemory(); else if (workspace.view === 'retro' && workspace.data) drawRetrospective(workspace.data); else if (workspace.view === 'requirements' && workspace.data) drawRequirements(workspace.data); },200);});
$('workspaceRefresh').addEventListener('click',loadWorkspace);
