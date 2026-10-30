'use strict';
/*
 * Вкладка «Статистика»: сколько, какие и когда задачи закрыл каждый демон.
 * Данные — /api/history (logs/*-history.jsonl, для старых инстансов — разбор логов).
 * Раздел «Что стало со сданными задачами» — в quality.js.
 */

const RESULT = {
  ok:   { label: tr('Готово', 'Done'),         icon: '✓', color: 'var(--st-good)' },
  warn: { label: tr('С замечаниями', 'With notes'),  icon: '⚠', color: 'var(--st-warn)' },
  fail: { label: tr('Ошибка', 'Failed'),         icon: '✗', color: 'var(--st-crit)' },
  blocked: { label: tr('Ждёт уточнения', 'Needs clarification'), icon: '?', color: 'var(--muted)' },
};
const PERIODS = [
  { key: 'today', label: tr('Сегодня', 'Today') }, { key: '7', label: tr('7 дней', '7 days') },
  { key: '30', label: tr('30 дней', '30 days') }, { key: 'all', label: tr('Всё время', 'All time') },
];
const stats = { period: '7', room: '', demon: '', query: '', data: null, timer: null, sort: 'done',
  prices: { input: 0, output: 0, cached: 0, currency: '₽' }, pricesOpen: false, serial: 0, direction: 1, error: '' };
function statsEditing() { return !!$('statsBody').querySelector('form, .name-input'); }
function statsEditorState() {
  const editing = statsEditing();
  $('stats').querySelectorAll('.filters input, .filters select, .filters button').forEach(el => { el.disabled = editing; });
  $('statsBody').querySelectorAll('[data-page-more]').forEach(el => { el.disabled = editing; });
  if (editing && $('statsStatus')) $('statsStatus').textContent = tr('Редактирование. Фильтры и автоматическое обновление приостановлены до сохранения или отмены.', 'Editing. Filters and automatic refresh are paused until you save or cancel.');
}
function statsStatus(message) { if ($('statsStatus')) $('statsStatus').textContent = message; }

// ------------------------------------------------------------------ стоимость
// Цены — за 1 млн токенов. Кэш считается частью входящих: вход берётся без кэша по цене входа,
// кэш — по своей цене. Если GigaCode сообщил только общее число токенов — оценка по цене входа.
const hasPrices = () => ['input', 'output', 'cached'].some((k) => Number(stats.prices[k]) > 0);
function taskCost(tok) {
  if (!tok || !hasPrices()) return null;
  const p = stats.prices, inp = tok.input, out = tok.output, cached = tok.cached || 0;
  if (inp == null && out == null) return tok.total ? { value: tok.total * p.input / 1e6, estimate: true } : null;
  const billable = Math.max(0, (inp || 0) - cached), cachedIn = Math.min(cached, inp || cached);
  return { value: (billable * p.input + cachedIn * p.cached + (out || 0) * p.output) / 1e6, estimate: false };
}
function fmtMoney(v) {
  if (v == null || !isFinite(v)) return '—';
  const digits = v < 1 ? 2 : v < 100 ? 1 : 0;
  return v.toLocaleString(uiLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits }) + ' ' + stats.prices.currency;
}
function costTitle(tok) {
  const c = taskCost(tok);
  if (!c) return '';
  if (c.estimate) return `${tr("оценка: ", "estimate: ")}${fmtTokens(tok.total)}${tr(" токенов × цена входа (вход/выход GigaCode не сообщил)", " tokens × input price (GigaCode did not report input/output separately)")}`;
  const p = stats.prices, cached = tok.cached || 0;
  return [`${tr("вход ", "input ")}${fmtTokens(Math.max(0, (tok.input || 0) - cached))} × ${p.input}`, cached ? `${tr("кэш ", "cache ")}${fmtTokens(cached)} × ${p.cached}` : '',
    `${tr("выход ", "output ")}${fmtTokens(tok.output || 0)} × ${p.output}`].filter(Boolean).join(' + ') + ` (${p.currency}${tr(" за 1 млн)", " per 1M)")}`;
}
// Стоимость задачи Jira — сумма по её попыткам (у каждой свои токены); у предложения — по его токенам
function recCost(r) {
  const runs = r.runs && r.runs.length ? r.runs : [r];
  let value = 0, estimate = false, counted = false;
  for (const run of runs) {
    const c = taskCost(run.tokens);
    if (c) { value += c.value; estimate = estimate || c.estimate; counted = true; }
  }
  return counted ? { value, estimate } : null;
}
function recCostTitle(r) {
  const runs = r.runs || [];
  if (runs.length < 2) return costTitle(r.tokens);
  const parts = runs.map((x, i) => { const c = taskCost(x.tokens); return `${tr("попытка ", "attempt ")}${i + 1}${x.result === 'fail' ? ' ✗' : ''}: ${c ? fmtMoney(c.value) : '—'}`; });
  return `${tr("сумма ", "total across ")}${runs.length}${tr(" попыток — ", " attempts — ")}${parts.join(' · ')}`;
}
function sumCost(recs) {
  let total = 0, counted = 0, estimated = 0;
  for (const r of recs) {
    const c = recCost(r);
    if (!c) continue;
    total += c.value; counted += 1; if (c.estimate) estimated += 1;
  }
  return { total, counted, estimated };
}
function renderPricesForm() {
  const p = stats.prices, f = (k, label) => `<label>${label}<input type="number" min="0" step="any" data-price="${k}" value="${p[k] || 0}"></label>`;
  return `<form class="prices" id="pricesForm">
    <div class="prices-title">${tr("Цена за 1 млн токенов", "Price per 1M tokens")}</div>
    ${f('input', tr('Входящие', 'Input'))}${f('output', tr('Исходящие', 'Output'))}${f('cached', tr('Кэш', 'Cache'))}
    <label>${tr("Валюта", "Currency")}<input type="text" maxlength="6" data-price="currency" value="${esc(p.currency || '₽')}"></label>
    <div class="form-actions"><button type="submit" class="btn primary">${tr("Сохранить", "Save")}</button><button type="button" class="btn" data-cancel-prices>${tr("Отмена", "Cancel")}</button></div>
    <span role="status" class="muted prices-note">${tr("Кэш считается частью входящих. Стоимость — оценка по расходу, который сообщил GigaCode.", "Cached tokens are part of input. Cost is estimated from usage reported by GigaCode.")}</span>
  </form>`;
}
async function savePrices(form) {
  const body = {};
  form.querySelectorAll('[data-price]').forEach(i => { body[i.dataset.price] = i.value; });
  const buttons = [...form.querySelectorAll('button')]; buttons.forEach(b => b.disabled = true);
  form.querySelector('.prices-note').textContent = tr('Сохранение…', 'Saving…');
  try {
    stats.prices = await workspaceJson('/api/prices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    markFormClean(form); stats.pricesOpen = false; renderStats(true); statsStatus(tr('Цены сохранены. Стоимость пересчитана.', 'Prices saved. Cost recalculated.'));
  } catch (e) { form.querySelector('.prices-note').textContent = tr('Не сохранено: ', 'Not saved: ') + translateServerMessage(e.message); buttons.forEach(b => b.disabled = false); }
}

function fmtMin(sec) {
  if (sec == null || !isFinite(sec)) return '—';
  const m = Math.round(sec / 60);
  if (m < 1) return tr('<1 мин', '<1 min');
  if (m < 60) return `${m}${tr(" мин", " min")}`;
  return `${Math.floor(m / 60)}${tr(" ч ", " h ")}${String(m % 60).padStart(2, '0')}${tr(" мин", " min")}`;
}
const pad2 = (n) => String(n).padStart(2, '0');
function fmtWhen(ts) {
  const d = new Date(ts * 1000), now = new Date();
  const time = d.toLocaleTimeString(uiLocale(), {hour:'2-digit', minute:'2-digit'});
  if (d.toDateString() === now.toDateString()) return `${tr("сегодня ", "today ")}${time}`;
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return `${tr("вчера ", "yesterday ")}${time}`;
  return `${d.toLocaleDateString(uiLocale(), {day:'numeric', month:'short'})} ${time}`;
}
const avg = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);
const dayStart = (ts) => { const d = new Date(ts * 1000); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };

function periodSince() {
  const now = Date.now() / 1000;
  if (stats.period === 'today') return dayStart(now);
  if (stats.period === 'all') return 0;
  return dayStart(now) - (Number(stats.period) - 1) * 86400;
}

function demonName(id) {
  const live = lastSnapshot.daemons.find((d) => d.id === id);
  const meta = (stats.data && stats.data.daemons[id]) || {};
  return (live && live.name) || meta.name || (live && live.project) || meta.project || id.toUpperCase();
}
function demonKey(id) {
  const live = lastSnapshot.daemons.find((d) => d.id === id);
  const meta = (stats.data && stats.data.daemons[id]) || {};
  const ci = (live && live.ci_id) || meta.ci_id;
  return ci ? `${tr("КЭ ", "CI ")}${ci}` : (live && live.project) || meta.project || id.toUpperCase();
}

async function loadStats() {
  if (statsEditing()) { statsEditorState(); return; }
  const serial = ++stats.serial, since = periodSince();
  const days = since ? (Date.now() / 1000 - since) / 86400 + 0.01 : 0;
  statsStatus(tr('Обновление…', 'Refreshing…'));
  if (!stats.data) $('statsBody').innerHTML = tr('<div class="workspace-loading" aria-label="Загрузка статистики"><span></span><span></span><span></span></div>', '<div class="workspace-loading" aria-label="Loading statistics"><span></span><span></span><span></span></div>');
  $('statsBody').setAttribute('aria-busy', 'true');
  try {
    const [data, prices] = await Promise.all([
      workspaceJson(`/api/history?days=${days.toFixed(3)}`),
      workspaceJson('/api/prices').catch(() => null)]);
    if (serial !== stats.serial) return;
    stats.data = data; stats.error = '';
    quality.key = null;
    if (prices) stats.prices = prices;
    renderStats();
    if (!statsEditing()) statsStatus(tr('Обновлено ', 'Updated ') + new Date().toLocaleTimeString(uiLocale(), {hour:'2-digit', minute:'2-digit'}) + tr(' · Период по последнему завершению задачи', ' · Period follows the latest task completion'));
  } catch (e) {
    if (serial !== stats.serial) return;
    stats.error = e.message;
    statsStatus(tr('История не обновлена: ', 'History was not refreshed: ') + translateServerMessage(e.message));
    if (!stats.data) $('statsBody').innerHTML = workspaceEmpty(tr('История временно недоступна', 'History is temporarily unavailable'), tr('Проверьте соединение с сервером и повторите загрузку.', 'Check the server connection and try loading again.')) + tr('<button class="btn" data-retry-stats>Повторить загрузку</button>', '<button class="btn" data-retry-stats>Retry loading</button>');
  } finally { if (serial === stats.serial) $('statsBody').setAttribute('aria-busy', 'false'); }
}

function inStatsOffice(id) { return !stats.room || ((lastSnapshot.office_memberships || {})[id] === stats.room || lastSnapshot.daemons.some(d => d.id === id && d.office_id === stats.room)); }
function filtered() {
  if (!stats.data) return [];
  const since = periodSince(), q = stats.query.trim().toLowerCase();
  return stats.data.records.filter((r) => r.finished_at >= since && inStatsOffice(r.id) && (!stats.demon || r.id === stats.demon) &&
    (!q || `${r.issue} ${r.message || ''} ${demonName(r.id)}`.toLowerCase().includes(q)));
}
function filteredProposals() {
  if (!stats.data || !stats.data.proposals) return [];
  const since = periodSince(), q = stats.query.trim().toLowerCase();
  return stats.data.proposals.filter((r) => r.finished_at >= since && inStatsOffice(r.id) && (!stats.demon || r.id === stats.demon) &&
    (!q || `${r.issue} ${r.summary || ''} ${demonName(r.id)}`.toLowerCase().includes(q)));
}
function statsPaginationKey() {
  return JSON.stringify([stats.period, stats.room, stats.demon, stats.query.trim().toLowerCase()]);
}

// ------------------------------------------------------------------ отрисовка
function renderStats(force=false) {
  if (statsEditing() && force !== true) { statsEditorState(); return; }
  const expanded = new Set([...$('statsBody').querySelectorAll('details[open][data-detail]')].map(d=>d.dataset.detail));
  if (lastSnapshot.offices && stats.room && !lastSnapshot.offices.some(r => r.id === stats.room)) { stats.room = ''; stats.demon = ''; }
  sectionPaginationContext('stats', statsPaginationKey());
  $('statsOffice').innerHTML = tr('<option value="">Все офисы</option>', '<option value="">All offices</option>') + (lastSnapshot.offices || []).map(r => `<option value="${esc(r.id)}"${stats.room === r.id ? ' selected' : ''}>${esc(r.title)}</option>`).join('');
  const recs = filtered(), props = filteredProposals();
  const ids = [...new Set([...lastSnapshot.daemons.map((d) => d.id), ...(stats.data ? stats.data.records.map((r) => r.id) : []),
    ...(stats.data && stats.data.proposals ? stats.data.proposals.map((r) => r.id) : [])])].filter(inStatsOffice).sort();
  $('statsDemon').innerHTML = tr('<option value="">Все демоны</option>', '<option value="">All daemons</option>') +
    ids.map((id) => `<option value="${esc(id)}"${stats.demon === id ? ' selected' : ''}>${esc(daemonOptionName(lastSnapshot.daemons.find(d=>d.id===id) || {id, name:demonName(id), project:stats.data?.daemons?.[id]?.project}))}</option>`).join('');
  if (!stats.data || (!stats.data.records.length && !(stats.data.proposals || []).length)) {
    $('statsBody').innerHTML = workspaceEmpty(tr('История работы пока пуста', 'No work history yet'), tr('Здесь появятся результаты задач, повторные попытки и расход токенов после первой завершённой работы.', 'Task results, retries, and token usage will appear here after the first completed job.')) + (stats.pricesOpen ? renderPricesForm() : tr('<button class="btn" data-prices>Настроить стоимость токенов</button>', '<button class="btn" data-prices>Set token prices</button>'));
    statsEditorState();
    return;
  }
  $('statsBody').innerHTML = `
    ${stats.pricesOpen ? renderPricesForm() : ''}
    <div class="kpis">${renderKpis(recs, props)}</div>
    ${!recs.length && !props.length ? workspaceEmpty(tr("Ничего не найдено", "Nothing found"), tr("Измените офис, демона или поисковый запрос.", "Change the office, daemon, or search.")) : ""}
    <div class="chart-row">
      <figure class="chart-card"><figcaption>${tr("Задачи по ", "Tasks by ")}${stats.period === 'today' ? tr('часам', 'hour') : tr('дням', 'day')}</figcaption>
        <div class="legend-row">${Object.values(RESULT).map((r) => `<span><i class="sw" style="background:${r.color}"></i>${r.icon} ${r.label}</span>`).join('')}</div>
        <div class="chart" id="chTime"></div></figure>
      <figure class="chart-card"><figcaption>${tr("Закрыто задач по демонам", "Completed tasks by daemon")}</figcaption>
        <div class="chart" id="chDemons"></div></figure>
    </div>
    <section class="table-card quality-card" id="qualityCard"></section>
    <section class="table-card"><h3>${tr("Демоны", "Daemons")}</h3>${renderDemonTable(recs, props)}</section>
    <section class="table-card"><h3>${tr("Журнал задач ", "Task journal ")}<span class="muted">${recs.length}${tr(" · одна строка — одна задача Jira, все её попытки", " · one row per Jira task, including all attempts")}</span></h3>
      ${renderJournal(recs)}</section>
    ${renderProposals(props)}`;
  drawTimeChart($('chTime'), recs);
  drawDemonChart($('chDemons'), recs);
  renderQuality();
  enhanceDataTables($('statsBody'));
  $('statsBody').querySelectorAll('details[data-detail]').forEach(d=>{d.open=expanded.has(d.dataset.detail);});
  statsEditorState();
}

// recs — задачи Jira (одна на задачу, итог — по последней попытке), props — прогоны исследования в простое
function renderKpis(recs, props) {
  const done = recs.filter((r) => ['ok','warn'].includes(r.result));
  const fails = recs.length - done.length;
  const failed = recs.filter(r => r.result === 'fail').length, blocked = recs.filter(r => r.result === 'blocked').length;
  const rate = recs.length ? Math.round(done.length / recs.length * 100) : 0;
  const firstTry = done.filter((r) => (r.failed_attempts || 0) === 0).length;
  const retried = done.length - firstTry;
  const failedRuns = recs.reduce((x, r) => x + (r.failed_attempts || 0), 0);
  const gen = avg(done.map((r) => r.gen_seconds).filter((x) => x != null));
  const deploys = recs.filter((r) => r.stand).length;
  const withTokens = recs.filter((r) => r.tokens && r.tokens.total);
  const taskTokens = withTokens.reduce((s2, r) => s2 + r.tokens.total, 0);
  const propTokens = props.reduce((x, p) => x + ((p.tokens && p.tokens.total) || 0), 0);
  const tile = (label, value, sub) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  return [
    tile(tr('Закрыто задач', 'Completed tasks'), done.length, `${tr("из ", "of ")}${recs.length}${tr(" задач Jira, взятых в работу", " Jira tasks taken on")}`),
    tile(tr('Успешность', 'Success rate'), recs.length ? `${rate}%` : '—', done.length
      ? `${tr("с первой попытки — ", "first attempt — ")}${Math.round(firstTry / done.length * 100)}% · ${recs.filter((r) => r.result === 'warn').length}${tr(" с замечаниями", " with notes")}` : ''),
    tile(tr('Не сделано', 'Not completed'), fails, [!fails ? tr('все задачи сделаны', 'all tasks completed') : '', failed ? `${failed}${tr(" — последняя попытка с ошибкой", " — latest attempt failed")}` : '',
      blocked ? `${blocked}${tr(" ждут уточнения в Jira", " awaiting clarification in Jira")}` : '', fails > failed + blocked ? `${fails - failed - blocked}${tr(" без итогового результата", " without a final result")}` : '',
      retried ? `${retried}${tr(" сделаны не с первой попытки", " completed after retrying")}` : '', failedRuns ? `${tr("неудачных попыток: ", "failed attempts: ")}${failedRuns}` : ''].filter(Boolean).join(' · ')),
    tile(tr('Среднее время генерации', 'Average generation time'), fmtMin(gen), tr('на задачу, все попытки', 'per task, all attempts')),
    tile(tr('Деплоев в Jenkins', 'Jenkins deployments'), deploys, deploys ? topStand(recs) : tr('нет лейблов jenkins_*', 'no jenkins_* labels')),
    tile(tr('Токенов потрачено', 'Tokens used'), withTokens.length || propTokens ? fmtTokens(taskTokens + propTokens) : '—', withTokens.length
      ? `≈ ${fmtTokens(taskTokens / withTokens.length)}${tr(" на задачу", " per task")}${withTokens.length < recs.length ? `${tr(" · учтено ", " · counted ")}${withTokens.length}${tr(" из ", " of ")}${recs.length}` : ''}${propTokens ? ` · ${fmtTokens(propTokens)}${tr(" — предложения", " — suggestions")}` : ''}`
      : (propTokens ? tr('только предложения в простое', 'idle suggestions only') : tr('GigaCode не сообщил расход', 'GigaCode did not report usage'))),
    proposalsTile(props, tile),
    costTile(recs, tile, props),
  ].join('');
}
// Стоимость за период: задачи (все попытки) + исследование бэклога в простое
function costTile(recs, tile, props = []) {
  const priceBtn = `<button class="link" data-prices>${hasPrices() ? tr('цены токенов', 'token prices') : tr('задать цены токенов', 'set token prices')}</button>`;
  if (!hasPrices()) return tile(tr('Стоимость', 'Cost'), '—', priceBtn);
  const c = sumCost(recs), pc = sumCost(props);
  if (!c.counted && !pc.counted) return tile(tr('Стоимость', 'Cost'), '—', `${tr("нет данных о токенах · ", "no token data · ")}${priceBtn}`);
  const sub = [c.counted ? `≈ ${fmtMoney(c.total / c.counted)}${tr(" на задачу", " per task")}` : '',
    c.counted < recs.length ? `${tr("учтено ", "counted ")}${c.counted}${tr(" из ", " of ")}${recs.length}` : '',
    pc.counted ? `${fmtMoney(pc.total)}${tr(" — предложения", " — suggestions")}` : '',
    c.estimated + pc.estimated ? `${c.estimated + pc.estimated}${tr(" — оценка по общему числу", " — estimated from total tokens")}` : '', priceBtn].filter(Boolean).join(' · ');
  return tile(tr('Стоимость', 'Cost'), (c.estimated || pc.estimated ? '≈ ' : '') + fmtMoney(c.total + pc.total), sub);
}
function topStand(recs) {
  const c = {};
  for (const r of recs) if (r.stand) c[r.stand] = (c[r.stand] || 0) + 1;
  const best = Object.entries(c).sort((a, b) => b[1] - a[1])[0];
  return best ? `${tr("чаще всего — ", "most frequent — ")}${best[0]}` : '';
}

function demonRows(recs, props = []) {
  const by = {}, pby = {};
  for (const r of recs) (by[r.id] ||= []).push(r);
  for (const p of props) { (pby[p.id] ||= []).push(p); by[p.id] ||= []; }
  if (!stats.demon) for (const d of lastSnapshot.daemons) if (inStatsOffice(d.id)) by[d.id] ||= [];
  return Object.entries(by).map(([id, rs]) => {
    const ps = pby[id] || [], pcost = sumCost(ps);
    const proposals = ps.filter((p) => p.result === 'posted').length;
    const retries = rs.reduce((x, r) => x + Math.max(0, (r.attempts || 1) - 1), 0);
    const ok = rs.filter((r) => r.result === 'ok').length, warn = rs.filter((r) => r.result === 'warn').length;
    const fail = rs.filter((r) => r.result === 'fail').length, done = ok + warn;
    const last = rs[0];
    const tk = rs.filter((r) => r.tokens && r.tokens.total).reduce((x, r) => x + r.tokens.total, 0);
    const cost = sumCost(rs);
    return { id, name: demonName(id), key: demonKey(id), done, ok, warn, fail, total: rs.length, tokens: tk,
      cost: cost.counted || pcost.counted ? cost.total + pcost.total : null, taskCost: cost.counted ? cost.total : null,
      propCost: pcost.counted ? pcost.total : null, proposals, retries,
      rate: rs.length ? done / rs.length : null, gen: avg(rs.filter((r) => ['ok','warn'].includes(r.result)).map((r) => r.gen_seconds)), last };
  });
}

function renderDemonTable(recs, props) {
  const rows = demonRows(recs, props);
  const sorters = { done: (a, b) => b.done - a.done, name: (a, b) => a.name.localeCompare(b.name, uiLocale()),
    rate: (a, b) => (b.rate ?? -1) - (a.rate ?? -1), gen: (a, b) => (a.gen ?? 1e12) - (b.gen ?? 1e12),
    tokens: (a, b) => b.tokens - a.tokens, cost: (a, b) => (b.cost ?? -1) - (a.cost ?? -1),
    proposals: (a, b) => b.proposals - a.proposals,
    last: (a, b) => ((b.last && b.last.finished_at) || 0) - ((a.last && a.last.finished_at) || 0) };
  rows.sort((a,b)=>(sorters[stats.sort] || sorters.done)(a,b)*stats.direction);
  const page = sectionPage('stats:demons', rows, JSON.stringify([statsPaginationKey(), stats.sort, stats.direction]), tr('Демоны', 'Daemons'));
  const th = (key, label, cls = '') => `<th scope="col" class="${cls}" aria-sort="${stats.sort === key ? ((['name','gen'].includes(key) ? stats.direction === 1 : stats.direction !== 1) ? 'ascending' : 'descending') : 'none'}"><button class="table-sort" data-sort="${key}">${label}<span aria-hidden="true">${stats.sort === key ? ((['name','gen'].includes(key) ? stats.direction === 1 : stats.direction !== 1) ? ' ↑' : ' ↓') : ' ↕'}</span></button></th>`;
  return `<div class="table-wrap"><table class="tbl"><thead><tr>${th('name', tr('Демон', 'Daemon'))}<th>${tr("КЭ / проект", "CI / project")}</th>${th('done', tr('Закрыто', 'Completed'), 'num')}
    <th class="num">${tr("Замечания", "Notes")}</th><th class="num">${tr("Ошибки", "Failures")}</th><th class="num" title="${tr("Сколько раз задачи брались заново после неудачи", "How often tasks were retried after a failure")}">${tr("Повторы", "Retries")}</th>${th('rate', tr('Успешность', 'Success rate'), 'num')}${th('gen', tr('Ср. генерация', 'Avg. generation'), 'num')}${th('tokens', tr('Токены', 'Tokens'), 'num')}${th('proposals', tr('Предложения', 'Suggestions'), 'num')}${th('cost', tr('Стоимость', 'Cost'), 'num')}
    ${th('last', tr('Последняя задача', 'Latest task'))}</tr></thead><tbody>${page.rows.map((r) => `<tr>
      <td><span class="name-cell" data-id="${esc(r.id)}">${esc(r.name)}</span>
        <button class="rename" data-rename="${esc(r.id)}" title="${tr("Изменить имя", "Rename")}" aria-label="${tr("Изменить имя ", "Rename ")}${esc(r.name)}">✎</button></td>
      <td class="muted">${esc(r.key)}</td><td class="num strong">${r.done}</td><td class="num">${r.warn || ''}</td>
      <td class="num">${r.fail || ''}</td><td class="num">${r.retries || ''}</td><td class="num">${r.rate == null ? '—' : Math.round(r.rate * 100) + '%'}</td>
      <td class="num">${fmtMin(r.gen)}</td><td class="num">${r.tokens ? fmtTokens(r.tokens) : '—'}</td>
      <td class="num">${r.proposals || ''}</td>
      <td class="num" title="${r.propCost ? `${tr("задачи ", "tasks ")}${fmtMoney(r.taskCost || 0)}${tr(" + предложения ", " + suggestions ")}${fmtMoney(r.propCost)}` : ''}">${r.cost == null ? '—' : fmtMoney(r.cost)}</td>
      <td>${r.last ? `${issueLink(r.last)} <span class="muted">${fmtWhen(r.last.finished_at)}</span>` : '<span class="muted">—</span>'}</td>
    </tr>`).join('')}</tbody></table></div>${page.footer}`;
}

// Попытки задачи: «3» и сколько из них ошибок; подсказка — каждая попытка с итогом и временем
function attemptsCell(r) {
  const n = r.attempts || 1, f = r.failed_attempts || 0;
  return n > 1 ? `${n}${f ? ` <span class="muted">(${f} ✗)</span>` : ''}` : '1';
}
function attemptsTitle(r) {
  const runs = r.runs || [];
  if (runs.length < 2) return '';
  return runs.map((x, i) => `${i + 1}. ${fmtWhen(x.finished_at)} — ${(RESULT[x.result] || RESULT.warn).label}` +
    `${x.gen_seconds ? `, ${fmtMin(x.gen_seconds)}` : ''}${x.message ? `: ${x.message}` : ''}`).join('\n');
}

function issueLink(r) {
  const base = stats.data && stats.data.daemons[r.id] && stats.data.daemons[r.id].jira_url;
  return base ? `<a href="${esc(base)}/browse/${encodeURIComponent(r.issue)}" target="_blank" rel="noopener">${esc(r.issue)}</a>` : esc(r.issue);
}

function renderJournal(recs) {
  const page = sectionPage('stats:journal', recs, statsPaginationKey(), tr('Журнал задач', 'Task journal')), rows = page.rows;
  if (!rows.length) return tr('<p class="muted pad">Задач с выбранными фильтрами нет.</p>', '<p class="muted pad">No tasks match the selected filters.</p>');
  return `<div class="table-wrap"><table class="tbl"><thead><tr><th>${tr("Когда", "When")}</th><th>${tr("Демон", "Daemon")}</th><th>${tr("Задача", "Task")}</th><th>${tr("Итог", "Outcome")}</th>
    <th class="num" title="${tr("Сколько раз демон брался за задачу", "How often the daemon attempted the task")}">${tr("Попыток", "Attempts")}</th><th class="num">${tr("Генерация", "Generation")}</th><th class="num">${tr("Всего", "Total")}</th><th class="num">${tr("Токены", "Tokens")}</th><th class="num">${tr("Стоимость", "Cost")}</th><th>${tr("Стенд", "Environment")}</th><th>${tr("Сообщение", "Message")}</th></tr></thead><tbody>
    ${rows.map((r) => { const res = RESULT[r.result] || RESULT.warn; return `<tr>
      <td class="nowrap">${fmtWhen(r.finished_at)}</td><td>${esc(demonName(r.id))}</td>
      <td class="nowrap">${issueLink(r)}${r.service ? ` <span class="svc">${esc(r.service)}</span>` : ''}</td>
      <td class="nowrap"><i class="sw" style="background:${res.color}"></i>${res.icon} ${res.label}</td>
      <td class="num">${(r.runs || []).length > 1 ? `<details class="attempt-details" data-detail="${esc(r.id+':'+r.issue+':runs')}"><summary>${attemptsCell(r)}</summary><div>${esc(attemptsTitle(r))}</div></details>` : attemptsCell(r)}</td>
      <td class="num">${fmtMin(r.gen_seconds)}</td><td class="num">${fmtMin(r.total_seconds)}</td>
      <td class="num" title="${r.tokens && r.tokens.input ? `${tr("вход ", "input ")}${r.tokens.input}${tr(" · выход ", " · output ")}${r.tokens.output}${r.tokens.cached ? `${tr(" · кэш ", " · cache ")}${r.tokens.cached}` : ''}` : ''}">${r.tokens && r.tokens.total ? fmtTokens(r.tokens.total) : '—'}</td>
      <td class="num" title="${esc(recCostTitle(r))}">${(() => { const c = recCost(r); return c ? (c.estimate ? '≈ ' : '') + fmtMoney(c.value) : '—'; })()}</td>
      <td>${r.stand ? esc(r.stand) + (r.migration ? tr(' <span class="muted">+ миграция</span>', ' <span class="muted">+ migration</span>') : '') : '<span class="muted">—</span>'}</td>
      <td class="msg" title="${esc(r.message || '')}">${esc(r.message || '')}</td></tr>`; }).join('')}
    </tbody></table></div>${page.footer}`;
}

// ------------------------------------------------------------------ графики (SVG)
const tip = () => $('chartTip');
function showTip(e, html) {
  const t = tip(); t.innerHTML = html; t.hidden = false;
  const r = t.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY - r.height - 10;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y < 8) y = e.clientY + 16;
  x = Math.max(8, Math.min(x, innerWidth - r.width - 8));
  y = Math.max(8, Math.min(y, innerHeight - r.height - 8));
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
const hideTip = () => { tip().hidden = true; };

function niceMax(v) {
  if (v <= 4) return Math.max(1, v);
  const p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
  return (n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

// Столбики по дням (или часам), сегменты — итоги задач; зазор 2px между сегментами
function drawTimeChart(el, recs) {
  const hourly = stats.period === 'today';
  const now = Date.now() / 1000;
  let start = hourly ? dayStart(now) : (stats.period === 'all'
    ? dayStart(Math.min(...recs.map((r) => r.finished_at), now)) : periodSince());
  const step = hourly ? 3600 : 86400;
  let n = Math.max(1, Math.ceil((now - start) / step));
  if (!hourly && n > 90) { start = dayStart(now) - 89 * 86400; n = 90; }
  const buckets = Array.from({ length: n }, (_, i) => ({ t: start + i * step, ok: 0, warn: 0, fail: 0, blocked: 0 }));
  for (const r of recs) {
    const i = Math.floor((r.finished_at - start) / step);
    if (i >= 0 && i < n) buckets[i][r.result in RESULT ? r.result : 'warn']++;
  }
  const W = el.clientWidth || 560, H = 220, L = 34, R = 8, T = 10, B = 26;
  const max = niceMax(Math.max(1, ...buckets.map((b) => b.ok + b.warn + b.fail + b.blocked)));
  const band = (W - L - R) / n, bw = Math.min(24, Math.max(3, band * 0.66));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, max / 2, max].filter((v, i, a) => a.indexOf(v) === i && Number.isInteger(v));
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${tr("Задачи по ", "Tasks by ")}${hourly ? tr('часам', 'hour') : tr('дням', 'day')}">`;
  for (const v of ticks) svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${L - 6}" y="${y(v) + 4}" class="axis" text-anchor="end">${v}</text>`;
  const labelEvery = Math.ceil(n / Math.max(1, Math.floor((W - L - R) / 46)));
  buckets.forEach((b, i) => {
    const x = L + i * band + (band - bw) / 2;
    let acc = 0;
    const segs = ['ok', 'warn', 'fail', 'blocked'].filter((k) => b[k] > 0);
    segs.forEach((k, si) => {
      const y0 = y(acc), y1 = y(acc + b[k]);
      const top = si === segs.length - 1, gap = si > 0 ? 2 : 0;
      const h = Math.max(0, y0 - y1 - gap);
      svg += top ? `<path d="${roundTop(x, y1, bw, h, Math.min(4, h, bw / 2))}" fill="${RESULT[k].color}"/>`
        : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" fill="${RESULT[k].color}"/>`;
      acc += b[k];
    });
    if (i % labelEvery === 0) {
      const d = new Date(b.t * 1000);
      const lab = hourly ? `${pad2(d.getHours())}:00` : d.toLocaleDateString(uiLocale(), {day:'2-digit', month:'2-digit'});
      svg += `<text x="${x + bw / 2}" y="${H - 8}" class="axis" text-anchor="middle">${lab}</text>`;
    }
    svg += `<rect x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}" class="hit" data-i="${i}"/>`;
  });
  svg += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" class="base"/></svg>`;
  el.innerHTML = svg;
  el.querySelectorAll('.hit').forEach((h) => {
    h.addEventListener('mousemove', (e) => {
      const b = buckets[+h.dataset.i], d = new Date(b.t * 1000);
      const title = hourly ? `${pad2(d.getHours())}:00–${pad2(d.getHours() + 1)}:00` : d.toLocaleDateString(uiLocale(), { weekday: 'short', day: 'numeric', month: 'long' });
      showTip(e, `<b>${title}</b>${['ok', 'warn', 'fail', 'blocked'].map((k) => `<div><i class="sw" style="background:${RESULT[k].color}"></i>${RESULT[k].icon} ${RESULT[k].label}: <b>${b[k]}</b></div>`).join('')}`);
    });
    h.addEventListener('mouseleave', hideTip);
  });
}
function roundTop(x, y, w, h, r) {
  if (h <= 0) return '';
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// Горизонтальные столбики: закрыто задач на демона (один ряд — один цвет)
function drawDemonChart(el, recs) {
  const rows = demonRows(recs).filter((r) => r.total > 0).sort((a, b) => b.done - a.done);
  if (!rows.length) { el.innerHTML = tr('<div class="muted pad">Нет задач за период</div>', '<div class="muted pad">No tasks in this period</div>'); return; }
  if (rows.length > 10) {
    el.insertAdjacentHTML('beforebegin', tr('<p class="chart-scroll-hint muted">Все демоны · список прокручивается</p>', '<p class="chart-scroll-hint muted">All daemons · scrollable list</p>'));
    el.tabIndex = 0; el.setAttribute('role', 'region');
    el.setAttribute('aria-label', tr('Закрытые задачи по всем демонам. Прокрутите список для просмотра остальных.', 'Completed tasks across all daemons. Scroll to see the rest.'));
  }
  const W = el.clientWidth || 420, rowH = 28, L = 110, R = 44, H = rows.length * rowH + 8;
  const max = Math.max(1, ...rows.map((r) => r.done));
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${tr("Закрыто задач по демонам", "Completed tasks by daemon")}">`;
  rows.forEach((r, i) => {
    const y = 4 + i * rowH, bw = Math.max(r.done ? 2 : 0, (W - L - R) * r.done / max);
    svg += `<text x="${L - 8}" y="${y + rowH / 2 + 4}" class="label" text-anchor="end"><title>${esc(r.name)} · ${esc(r.id)} · ${esc(r.key)}</title>${esc(r.name.length > 14 ? r.name.slice(0, 13) + '…' : r.name)}</text>`;
    if (bw > 0) svg += `<path d="${roundRight(L, y + 5, bw, rowH - 10, Math.min(4, bw))}" fill="var(--series-1)"/>`;
    svg += `<text x="${L + bw + 6}" y="${y + rowH / 2 + 4}" class="value">${r.done}</text>`;
    svg += `<rect x="0" y="${y}" width="${W}" height="${rowH}" class="hit" data-i="${i}"/>`;
  });
  el.innerHTML = svg + '</svg>';
  el.querySelectorAll('.hit').forEach((h) => {
    h.addEventListener('mousemove', (e) => {
      const r = rows[+h.dataset.i];
      showTip(e, `<b>${esc(r.name)}</b> <span class="muted">${esc(r.key)}</span>
        <div>${tr("Закрыто: ", "Completed: ")}<b>${r.done}</b> (⚠ ${r.warn}) · ✗ ${r.fail}</div><div>${tr("Ср. генерация: ", "Avg. generation: ")}<b>${fmtMin(r.gen)}</b></div>
        <div>${tr("Токены: ", "Tokens: ")}<b>${r.tokens ? fmtTokens(r.tokens) : '—'}</b></div>${r.cost != null ? `<div>${tr("Стоимость: ", "Cost: ")}<b>${fmtMoney(r.cost)}</b></div>` : ''}`);
    });
    h.addEventListener('mouseleave', hideTip);
  });
}
function roundRight(x, y, w, h, r) {
  return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
}

// ------------------------------------------------------------------ вкладки и фильтры
function setView(view) {
  const changed = workspace.view !== view;
  const isStats = view === 'stats';
  const extra = ['analytics', 'retro', 'memory', 'requirements'].includes(view);
  showWorkspace(view);
  if (typeof showPrompts === 'function') showPrompts(view);
  document.body.classList.toggle('view-stats', isStats || extra || view === 'prompts');
  $('stats').hidden = !isStats;
  document.querySelectorAll('.view-tab').forEach(b => {
    const active = b.dataset.view === view; b.classList.toggle('on', active);
    b.setAttribute('aria-pressed', String(active));
    if (active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  if ($('teamTools')) $('teamTools').hidden = view !== 'office';
  hideTip();
  if (changed) {
    const main = document.querySelector('.app-main');
    if (main) main.scrollTop = 0;
  }
  window.dispatchEvent(new CustomEvent('artel:view-changed', {detail:{view}}));
  try { localStorage.setItem('office-view', view); } catch { /* нет хранилища */ }
  clearInterval(stats.timer);
  if (isStats) { closeDrawer(); loadStats(); stats.timer = setInterval(()=>{ if (!document.hidden && !statsEditing()) loadStats(); }, 30000); }
  else if (extra || view === 'prompts') { closeDrawer(); }
  else { renderBuilding(); syncOffice(); window.dispatchEvent(new Event('resize')); }
}

function setupStats() {
  $('statsCsv').title = tr('Выгрузить все задачи выбранного периода, офиса и демона. Текстовый поиск не применяется.', 'Export all tasks for the selected period, office, and daemon. Text search does not apply.');
  $('statsPeriods').innerHTML = PERIODS.map((p) => `<button data-period="${p.key}" aria-pressed="${stats.period === p.key}" class="${stats.period === p.key ? 'on' : ''}">${p.label}</button>`).join('');
  $('statsPeriods').addEventListener('click', (e) => {
    const b = e.target.closest('[data-period]'); if (!b) return;
    stats.period = b.dataset.period;
    $('statsPeriods').querySelectorAll('button').forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); });
    loadStats();
  });
  $('officeStats').onclick = () => { stats.room = buildingView.room || ''; stats.demon = ''; setView('stats'); };
  $('statsOffice').onchange = e => { stats.room = e.target.value; stats.demon = ''; renderStats(); };
  $('statsDemon').addEventListener('change', (e) => { stats.demon = e.target.value; renderStats(); });
  $('statsSearch').addEventListener('input', (e) => { stats.query = e.target.value; renderStats(); });
  $('statsCsv').addEventListener('click', () => {
    const since = periodSince(), days = since ? (Date.now() / 1000 - since) / 86400 + 0.01 : 0;
    location.href = `/api/history.csv?${new URLSearchParams({days:days.toFixed(3),office:stats.room,id:stats.demon,lang:uiLocale().split('-')[0]})}`;
  });
  $('statsBody').addEventListener('submit', (e) => {
    if (e.target.id === 'pricesForm') { e.preventDefault(); savePrices(e.target); }
  });
  $('statsBody').addEventListener('click', (e) => {
    if (sectionPaginationClick(e, key => key === 'stats:quality' ? drawQuality() : renderStats(), () => !statsEditing())) return;
    if (e.target.closest('[data-retry-stats]')) { loadStats(); return; }
    if (e.target.closest('[data-cancel-prices]')) { markFormClean($('pricesForm')); stats.pricesOpen = false; renderStats(true); statsStatus(tr('Изменения цен отменены.', 'Price changes cancelled.')); return; }
    if (e.target.closest('[data-prices]')) {
      if (statsEditing()) return;
      stats.pricesOpen = true; renderStats(); $('pricesForm')?.querySelector('input')?.focus(); return;
    }
    const th = e.target.closest('[data-sort]');
    if (th) { if (statsEditing()) return; stats.direction = stats.sort === th.dataset.sort ? -stats.direction : 1; stats.sort = th.dataset.sort; renderStats(); return; }
    const b = e.target.closest('[data-rename]'); if (!b || statsEditing()) return;
    const id = b.dataset.rename, cell = b.parentElement;
    const d = lastSnapshot.daemons.find((x) => x.id === id) || { id, project: demonKey(id), name: null };
    if (!d.name && demonName(id) !== demonKey(id)) d.name = demonName(id);
    startRename(cell, d, () => { renderStats(true); loadStats(); });
    statsEditorState();
  });
  document.querySelectorAll('.view-tab').forEach((b) => b.addEventListener('click', () => { setView(b.dataset.view); if (b.dataset.view === 'office') openOffice(null); }));
  let statsResizeTimer;
  window.addEventListener('resize', () => { clearTimeout(statsResizeTimer); statsResizeTimer=setTimeout(()=>{ if (!$('stats').hidden && stats.data && !statsEditing()) renderStats(); },150); });
  let saved = 'office';
  try { saved = localStorage.getItem('office-view') || 'office'; } catch { /* нет хранилища */ }
  if (['stats', 'analytics', 'retro', 'memory', 'requirements', 'prompts'].includes(saved)) setView(saved);
}

setupStats();
