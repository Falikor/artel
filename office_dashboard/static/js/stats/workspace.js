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
  if (editing) $('workspaceStatus').textContent = 'Изменения ещё не сохранены. Обновление и фильтры приостановлены до сохранения или отмены.';
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
    wrap.setAttribute('aria-label', 'Таблица данных. При необходимости прокрутите по горизонтали.');
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
  try { data = await response.json(); } catch { throw new Error('Сервер вернул неожиданный ответ. Повторите попытку.'); }
  if (!response.ok || data.error) throw new Error(data.error || data.reason || 'Сервер недоступен (HTTP ' + response.status + ')');
  return data;
}
function daemonOptionName(d) {
  const name = displayName(d), parts = [name];
  if (d.project && d.project !== name) parts.push(d.project);
  if (d.id && d.id !== name) parts.push(d.id);
  return parts.join(' · ');
}
const memoryLabels = {candidate: 'Кандидат', confirmed: 'Подтверждено', rejected: 'Отклонено'};
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
  const names = {requirements: ['Переделки по новой постановке', 'Отдельная очередь запросов. Демон начинает переделку после текущей работы. Ошибки не запускают автоматический повтор.'],
    analytics: ['Аналитика работы', 'Сколько времени и попыток требуют задачи. Период определяется по последнему завершению задачи.'],
    memory: ['Память демонов', 'Проверенные знания и кандидаты в уроки. Автоматическая проверка оставляет вам только спорные решения.'],
    retro: ['Ретроспектива', 'Что произошло со сданными задачами: слияния, правки и доработки. Исходы определяются по истории Git.']};
  $('workspaceTitle').textContent = names[view][0]; $('workspaceHint').textContent = names[view][1];
  $('workspaceDays').hidden = view === 'memory';
  $('workspaceSearch').hidden = view === 'analytics';
  $('workspaceSearch').placeholder = view === 'memory' ? 'Найти урок или задачу' : view === 'retro' ? 'Найти задачу, ветку или демона' : 'Найти задачу или постановку';
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
  if (!$('workspaceBody').childNodes.length) $('workspaceBody').innerHTML = '<div class="workspace-loading" aria-label="Загрузка данных"><span></span><span></span><span></span></div>';
  $('workspaceStatus').textContent = 'Загрузка данных…';
  try {
    const state = await workspaceJson('/api/state');
    if (workspace.view !== view) return;
    workspaceSelect('workspaceOffice', (state.offices || []).map(x => ({id:x.id, name:x.title})), 'Все офисы');
    workspaceSelect('workspaceDaemon', (state.daemons || []).map(d => ({id:d.id, name:daemonOptionName(d)})), 'Все демоны');
    await loadWorkspace();
  } catch (e) {
    if (workspace.view !== view) return;
    $('workspaceStatus').textContent = 'Не удалось загрузить данные: ' + e.message;
    if (!workspace.data) workspaceRender(workspaceEmpty('Данные временно недоступны', 'Проверьте соединение с сервером и нажмите «Обновить».'));
  }
  if (workspace.view === view) workspace.timer = setInterval(() => { if (!document.hidden && !workspaceEditing()) loadWorkspace(); }, 30000);
}
function metric(label, value, note='') {
  return `<div class="kpi"><div class="kpi-label">${esc(label)}</div><div class="kpi-value">${esc(String(value ?? '—'))}</div><div class="kpi-sub">${esc(note)}</div></div>`;
}
function minutes(n) { return n == null ? '—' : (n / 60).toLocaleString('ru-RU', {maximumFractionDigits:1}) + ' мин'; }
function workspaceTable(head, rows) {
  return `<div class="table-wrap"><table class="workspace-table"><thead><tr>${head.map(h => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}
async function loadWorkspace(force=false) {
  if (workspaceEditing() && force !== true) { workspaceEditorState(); return; }
  const serial = ++workspace.serial, view = workspace.view;
  if (!workspaceViews.includes(view)) return;
  $('workspaceStatus').textContent = 'Обновление…';
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
    if (!workspaceEditing()) $('workspaceStatus').textContent = 'Обновлено ' + new Date().toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'});
    return true;
  } catch (e) {
    if (serial !== workspace.serial) return;
    $('workspaceStatus').textContent = 'Данные не обновлены: ' + e.message;
    if (!workspace.data) workspaceRender(workspaceEmpty('Не удалось загрузить раздел', 'Проверьте соединение и нажмите «Обновить».'));
    return false;
  } finally { if (serial === workspace.serial) $('workspaceBody').setAttribute('aria-busy', 'false'); }
}
function drawAnalytics(data) {
  const t = data.totals;
  const page = sectionPage('workspace-analytics:groups', data.groups, workspacePaginationKey(), 'Аналитика по демонам и сервисам');
  if (!t.tasks) { workspaceRender(workspaceEmpty('За этот период ещё нет завершённых попыток', 'Выберите другой период или офис. Здесь появятся время работы, расход токенов и повторные попытки.')); return; }
  const money = t.cost == null ? '—' : t.cost.toLocaleString('ru-RU', {maximumFractionDigits:2}) + ' ' + t.currency;
  workspaceRender(`<div class="kpis">${metric('Задач', t.tasks, `${t.completed} завершены успешно или с замечаниями`)}${metric('Попыток', t.attempts, `${t.failed_attempts} неудачных`)}${metric('С первой попытки', t.first_pass, `из ${t.completed} завершённых`)}${metric('Медиана времени', minutes(t.median_seconds))}${metric('90-й перцентиль', minutes(t.p90_seconds), '90% задач заняли не больше этого времени')}${metric('Токены', t.tokens.toLocaleString('ru-RU'), `известны для ${t.token_coverage} из ${t.attempts} попыток`)}${metric('Оценка стоимости', money, `учтено задач: ${t.cost_coverage} из ${t.tasks}; цены задаются в Статистике`)}</div>` +
    workspaceTable(['Демон / сервис', 'Задач', 'Попыток', 'Неудачных попыток', 'Медиана', 'P90', 'Токены'], page.rows.map(g => `<tr>${[demonName(g.id) + (g.service ? ' / ' + g.service : ''), g.tasks, g.attempts, g.failed_attempts, minutes(g.median_seconds), minutes(g.p90_seconds), g.tokens.toLocaleString('ru-RU')].map(v => `<td>${esc(String(v))}</td>`).join('')}</tr>`)) + page.footer);
}
function drawRetrospective(data) {
  const t = data.summary.totals, labels = {as_is:'Слито без правок', changed:'Слито с правками', dropped:'Удалено без слияния', open:'Ещё открыто', waiting:'Ожидает проверки', unknown:'Исход неизвестен'};
  const query = $('workspaceSearch').value.trim().toLowerCase();
  const rows = data.rows.filter(r => JSON.stringify([r.issue, r.id, demonName(r.id), r.branch, labels[r.category]]).toLowerCase().includes(query));
  const page = sectionPage('workspace-retro:tasks', rows, workspacePaginationKey(), 'Ретроспектива');
  workspaceRender(`<div class="kpis">${Object.entries(labels).map(([k,l]) => metric(l,t[k])).join('')}</div>` + (rows.length ? workspaceTable(['Задача / демон', 'Исход', 'Правки людей', 'Доработки', 'Последняя проверка', 'Подробности'], page.rows.map(r => `<tr><td><strong>${esc(r.issue)}</strong><br>${esc(r.id)} ${esc(r.service || '')}</td><td>${esc(labels[r.category] || r.category)}</td><td>${esc(String(r.human_commits))} коммитов<br>≈ ${esc(String(r.human_lines))} строк</td><td>${esc(String(r.followups))}</td><td>${r.checked_at ? esc(new Date(r.checked_at * 1000).toLocaleString('ru-RU')) : 'Ещё не проверена'}</td><td><details data-detail="${esc(r.id + ":" + r.issue)}"><summary>Ветка и сдача</summary><p>${esc(r.branch || '—')}</p><p>База: ${esc(r.base || '—')}</p><p>Коммит: <code>${esc(r.head || '—')}</code></p><p>Сдана: ${esc(new Date(r.delivered_at * 1000).toLocaleString('ru-RU'))}</p><p>Jira: ${esc(r.jira_status || 'неизвестно')}</p></details></td></tr>`)) + page.footer : workspaceEmpty('Сданных задач не найдено', 'Измените период, офис или поисковый запрос. Ретроспектива появится после сдачи и проверки задачи.')));
}
function drawMemory() {
  const data = workspace.memory;
  if (!data) return;
  if (!data.available) { workspaceRender(workspaceEmpty('Память в этом режиме недоступна', 'Откройте основной дашборд рядом с конфигурациями демонов. Демо показывает интерфейс без доступа к рабочим знаниям.')); return; }
  const filter = $('memoryFilter').value, query = $('workspaceSearch').value.trim().toLowerCase();
  const pageKey = workspacePaginationKey();
  let count = 0, disputed = 0, confirmed = 0;
  const emptySources = [];
  const cards = data.sources.map(source => {
    const entries = source.entries.filter(e => {
      count++; if (e.needs_review) disputed++; if (e.status === 'confirmed') confirmed++;
      return (!filter || (filter === 'disputed' ? e.needs_review : e.status === filter)) && JSON.stringify(e).toLowerCase().includes(query);
    });
    const page = sectionPage('workspace-memory:source:' + source.key, entries, pageKey, 'Уроки: ' + (source.name || source.id));
    if (!source.entries.length && !source.error && !source.legacy) { emptySources.push(source); return ''; }
    if (!entries.length && !source.error && !source.legacy && (query || filter)) return '';
    return `<section class="memory-source"><div class="memory-source-head"><h3>${esc(source.name || source.id)}</h3><span class="muted">${esc(source.service || source.id)}</span><span class="memory-count">${entries.length} записей</span></div>${source.error ? `<p>${esc(source.error)}</p>` : ''}${source.legacy ? '<p>Есть прежние заметки: демон импортирует их при следующем обращении к памяти.</p>' : ''}${page.rows.map(e => `<article class="memory-entry"><div><span class="tag">${esc(memoryLabels[e.status] || e.status)}</span> ${e.needs_review ? '<strong class="needs-review">Нужно ваше решение</strong>' : ''}</div><h4>${esc(e.text)}</h4><p class="muted">Задача: ${esc(e.issue || '—')} · Источник: ${esc(e.source || '—')} · Наблюдений: ${esc(String(e.observations || 1))}</p><p>Область: ${esc((e.scope || []).join(', ') || 'общая')}</p><details data-detail="${esc(source.key + ":" + e.id)}"><summary>Основание и проверка</summary><p>${esc(e.evidence || 'Основание ещё не записано')}</p><pre>${esc(JSON.stringify(e.verification || {}, null, 2))}</pre></details>${data.control ? `<div class="memory-actions" data-source="${esc(source.key)}" data-entry="${esc(e.id)}">${e.status === 'candidate' ? '<button class="btn" data-memory-action="retry">Проверить повторно</button>' : ''}${e.status !== 'confirmed' ? '<button class="btn" data-memory-action="approve">Подтвердить с основанием</button>' : ''}${e.status !== 'rejected' ? '<button class="btn" data-memory-action="reject">Отклонить</button>' : ''}</div>` : ''}</article>`).join('') || '<p class="muted">Записей с такими фильтрами нет.</p>'}${page.footer}</section>`;
  }).join('');
  const emptyPage = sectionPage('workspace-memory:empty-sources', emptySources, pageKey, 'Демоны без записей');
  const emptyList = emptySources.length ? `<details class="empty-sources" data-detail="empty-sources"><summary>Демоны без записей · ${emptySources.length}</summary><p class="muted">Память появится после работы над задачами и проверки предложенных уроков.</p><ul>${emptyPage.rows.map(source=>`<li><strong>${esc(source.name || source.id)}</strong><span>${esc([source.service,source.id].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>${emptyPage.footer}</details>` : '';
  workspaceRender(`<div class="kpis">${metric('Записей',count)}${metric('Подтверждено',confirmed)}${metric('Спорных',disputed)}</div>` + (cards || workspaceEmpty(query || filter ? 'Подходящих уроков не найдено' : 'Уроков пока нет', query || filter ? 'Измените статус, поисковый запрос или фильтры.' : 'После работы над задачами демоны предложат знания и проверят их по коду и тестам. Спорные записи появятся здесь.')) + emptyList);
}
async function memoryAction(source, entry, action, evidence='', scope=[]) {
  const response = await fetch('/api/memory', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source, entry, action, evidence, scope})});
  if (!response.ok) throw new Error('HTTP ' + response.status);
  const result = await response.json();
  if (!result.ok) throw new Error(result.error || result.reason || 'Решение не сохранено');
  delete workspace.cache.memory;
  if (workspace.view === 'memory') {
    // The POST already succeeded. Close the editor before the optional refresh,
    // so a failed GET cannot leave a saved lesson locked in a disabled form.
    $('workspaceBody').querySelectorAll('[data-source][data-entry]').forEach(container => {
      if (container.dataset.source === source && container.dataset.entry === entry) container.textContent = 'Решение сохранено.';
    });
    workspaceEditorState();
    const refreshed = await loadWorkspace(true);
    $('workspaceStatus').textContent = refreshed ? 'Решение сохранено.' : 'Решение сохранено. ' + $('workspaceStatus').textContent + ' Нажмите «Обновить», чтобы получить актуальные записи.';
  }
}
$('workspaceBody').addEventListener('click', async event => {
  if (sectionPaginationClick(event, redrawWorkspace, () => !workspaceEditing())) return;
  const button = event.target.closest('[data-memory-action]'); if (!button) return;
  const container = button.closest('[data-source]'), {source,entry} = container.dataset, action = button.dataset.memoryAction;
  if (action === 'approve') {
    container.innerHTML = '<form class="memory-approval"><label>Основание решения<textarea name="evidence" required maxlength="1000" placeholder="Что проверено: код, тесты, принятое решение"></textarea></label><label>Области применения через запятую<input name="scope" maxlength="1000"></label><div class="form-actions"><button class="btn primary">Подтвердить урок</button><button class="btn" type="button" data-memory-action="cancel">Отмена</button></div><p class="form-status" role="status"></p></form>';
    const lesson = workspace.memory?.sources.find(item => item.key === source)?.entries.find(item => item.id === entry);
    container.querySelector('[name=scope]').value = (lesson?.scope || []).join(', ');
    container.querySelector('textarea').focus(); workspaceEditorState(); return;
  }
  if (action === 'cancel') { drawMemory(); workspaceEditorState(); $('workspaceStatus').textContent = 'Изменение урока отменено.'; return; }
  if (action === 'reject') {
    container.innerHTML = '<form class="memory-rejection"><p>Отклонить этот урок? Демон перестанет использовать его как знание. Запись останется в истории.</p><div class="form-actions"><button class="btn" type="submit">Отклонить урок</button><button class="btn" type="button" data-memory-action="cancel">Отмена</button></div><p role="status"></p></form>';
    workspaceEditorState(); container.querySelector('button').focus(); return;
  }
  button.disabled = true;
  try { await memoryAction(source,entry,action); } catch(e) { $('workspaceStatus').textContent=e.message; button.disabled=false; }
});
$('workspaceBody').addEventListener('submit', async event => {
  if (!event.target.matches('.memory-approval, .memory-rejection')) return;
  const form=event.target, container=form.closest('[data-source]');
  if (!container) return; // Other workspace forms share the layout class, not the memory action.
  event.preventDefault();
  form.querySelectorAll('button').forEach(b=>b.disabled=true);
  try { await memoryAction(container.dataset.source, container.dataset.entry, form.matches('.memory-rejection') ? 'reject' : 'approve', form.elements.evidence?.value || '', (form.elements.scope?.value || '').split(',').map(x=>x.trim()).filter(Boolean)); }
  catch(e) { form.querySelector('[role=status]').textContent=e.message; form.querySelectorAll('button').forEach(b=>b.disabled=false); }
});
['workspaceDays','workspaceOffice','workspaceDaemon'].forEach(id=>$(id).addEventListener('change',()=>loadWorkspace()));
$('memoryFilter').addEventListener('change',()=>{ if (!workspaceEditing()) drawMemory(); });
let workspaceSearchTimer;
$('workspaceSearch').addEventListener('input',()=>{clearTimeout(workspaceSearchTimer);workspaceSearchTimer=setTimeout(()=>{ if (workspaceEditing()) return; if (workspace.view === 'memory') drawMemory(); else if (workspace.view === 'retro' && workspace.data) drawRetrospective(workspace.data); else if (workspace.view === 'requirements' && workspace.data) drawRequirements(workspace.data); },200);});
$('workspaceRefresh').addEventListener('click',loadWorkspace);
