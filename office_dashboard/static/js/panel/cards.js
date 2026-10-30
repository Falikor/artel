'use strict';
/* Карточки демонов справа: этап, простой, версия, легенда; «проверить Jira сейчас». */

// ------------------------------------------------------------------ панель
// ------------------------------------------------------------------ простой
const IDLE_STAGES = new Set(['idle', 'polling', 'starting', 'exploring', 'retro']);
// Секунды с последней реальной задачи (исследование бэклога и опросы Jira простоем считаются);
// если задач ещё не было — с запуска демона
function idleSeconds(d) {
  const since = (d.last_task && d.last_task.finished_at) || d.started_at;
  return since ? Math.max(0, nowSec() - since) : null;
}
function fmtIdle(sec) {
  const m = Math.floor(sec / 60);
  if (m < 1) return tr("меньше минуты","less than a minute");
  if (m < 60) return `${m} ${tr('мин','min')}`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ${tr('ч','h')} ${String(m % 60).padStart(2, '0')} ${tr('мин','min')}`;
  return `${Math.floor(h / 24)} ${tr('д','d')} ${h % 24} ${tr('ч','h')}`;
}

// Самая новая версия кода среди демонов: остальные помечаются «устарел»
let newestVersion = null;
function cmpVersion(a, b) {
  const pa = String(a).split('.').map((x) => parseInt(x, 10) || 0), pb = String(b).split('.').map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  return 0;
}
function outdated(d) {
  return !!(d.daemon_version && newestVersion && d.alive !== false && cmpVersion(d.daemon_version, newestVersion) < 0);
}

function renderCards() {
  const box = $('cards');
  if (!buildingView.room) { box.innerHTML = ''; return; }
  const allDaemons = visibleDaemons();
  const daemons = filteredDaemons(allDaemons);
  newestVersion = allDaemons.map((d) => d.daemon_version).filter(Boolean).sort(cmpVersion).pop() || null;
  if (!daemons.length) {
    box.innerHTML = `<div class="empty">${allDaemons.length ? tr('Нет демонов с такими условиями. Измените запрос или статус в поиске.','No daemons match these filters. Change the search or status.') : tr('В этом офисе пока нет демонов. Переселите их из другого офиса в разделе «Здание».','This office is empty. Move daemons from another office in the building view.')}</div>`;
    $('summary').innerHTML = '';
    return;
  }
  const t = nowSec();
  const counts = {};
  const html = daemons.map((d) => {
    const w = office.workers.get(d.id);
    const stage = d.alive === false && d.stage !== 'stopped' ? 'lost' : d.stage;
    counts[stage] = (counts[stage] || 0) + 1;
    const info = STAGE[stage] || STAGE.idle;
    const c = d.counters || {};
    const res = d.last_result;
    const resHtml = res ? `<span class="${['ok','warn','fail'].includes(res.result) ? res.result : 'fail'}">${res.result === 'ok' ? '✓' : res.result === 'warn' ? '⚠' : '✗'} ${esc(res.issue)}</span>` : '';
    const next = d.next_poll_at || (d.detail || {}).next_poll_at;
    // В простое — сколько демон без реальной задачи (с последней закрытой задачи), а не таймеры опроса
    const idleStage = IDLE_STAGES.has(stage), idle = idleStage ? idleSeconds(d) : null;
    const idleTitle = next ? ` title="${tr('следующий опрос Jira через','next Jira check in')} ${fmtDur(Math.max(0, next - t))}"` : '';
    const idleText = idle == null ? '' : `${tr('простой','idle for')} ${fmtIdle(idle)}${d.last_task && d.last_task.issue
      ? ` <span class="muted">· ${tr('после','after')} ${esc(d.last_task.issue)}</span>` : ` <span class="muted">· ${tr('с запуска','since startup')}</span>`}`;
    let issueLine = '';
    if (d.issue) issueLine = `<span class="key">${esc(d.issue)}</span><span>${esc(info.label)}${(d.detail || {}).service ? ` · ${esc(d.detail.service)}` : ''}</span>`;
    else if (stage === 'retro') issueLine = `<span${idleTitle}>${tr('ретроспектива: что стало с задачами','retrospective: task outcomes')} (${(d.detail || {}).tasks || '…'}) · ${idleText}</span>`;
    else if (idleStage && w && w.plan && w.plan.kind && !w.visible) issueLine = `<span${idleTitle}>${tr('вышел из офиса','outside the office')} · ${idleText}</span>`;
    else if (idleStage && idleText) issueLine = `<span${idleTitle}>${idleText}</span>`;
    else if (stage === 'lost') issueLine = `<span>heartbeat ${fmtDur(d.heartbeat_age || 0)} ${tr('назад','ago')}</span>`;
    // Ошибку показываем и вне этапа error, если она свежая (например, Jira недоступна при опросе)
    const errFresh = d.last_error && (stage === 'error' || stage === 'lost' || t - d.last_error.t < 15 * 60);
    const err = errFresh ? `<div class="card-err${stage === 'error' || stage === 'lost' ? '' : ' soft'}" title="${esc(d.last_error.message)}">${esc(d.last_error.message)}</div>` : '';
    const meta = [
      d.guest ? `<span>${tr('В гостях · своё место сохранено','Visiting · permanent seat preserved')}</span>` : Number.isInteger(d.office_slot) ? `<span>${tr('Место','Seat')} ${d.office_slot + 1}</span>` : '',
      d.counters ? `<span title="${tr('задач Jira с запуска демона: готово / с замечаниями / не сделано (итог — по последней попытке)','Jira tasks since startup: done / with issues / not completed (latest attempt)')}">✓ ${c.done || 0} · ⚠ ${c.warn || 0} · ✗ ${c.failed || 0}</span>` : '',
      c.tokens ? `<span title="${tr('токенов GigaCode с запуска демона','GigaCode tokens since startup')}">◆ ${fmtTokens(c.tokens)}</span>` : '',
      resHtml,
      d.source === 'log' ? `<span title="${tr('state-файла нет, этапы восстановлены из лога','No state file; stages inferred from logs')}">${tr('по логу','from logs')}</span>` : '',
      d.daemon_version ? `<span class="${outdated(d) ? 'outdated' : ''}" title="${outdated(d) ? tr(`версия кода новее (${esc(newestVersion)}) — перезапустите демона: python3 artel.py restart --outdated`,`Newer code available (${esc(newestVersion)}) — restart: python3 artel.py restart --outdated`) : tr('версия кода демона','daemon code version')}">v${esc(d.daemon_version)}${outdated(d) ? ' ⚠' : ''}</span>` : '',
    ].filter(Boolean).join('');
    return `<div class="card${office.selected === d.id ? ' sel' : ''}${stage === 'stopped' || stage === 'lost' ? ' off' : ''}" data-id="${esc(d.id)}" role="button" tabindex="0" aria-label="${esc(displayName(d))}: ${esc(info.label)}. ${tr('Открыть панель демона','Open daemon panel')}" aria-expanded="${office.selected === d.id}" style="--c:${info.color}">
      <div class="card-row"><span class="card-name">${esc(displayName(d))}</span>${d.name ? `<span class="card-key">${esc(projectKey(d))}</span>` : ''}
        <span class="card-stage">${esc(info.label)}</span></div>
      ${issueLine ? `<div class="card-issue">${issueLine}${idleStage && !d.issue ? '' : `<span class="time">${fmtDur(t - (d.stage_since || t))}</span>`}</div>` : ''}
      ${meta ? `<div class="card-meta">${meta}</div>` : ''}${err}
    </div>`;
  }).join('');
  replaceRosterContent(box, html);
  const chip = (stages, label, color) => {
    const n = stages.reduce((s, k) => s + (counts[k] || 0), 0);
    return n ? `<span class="chip"><i style="background:${color}"></i>${label} <b>${n}</b></span>` : '';
  };
  $('summary').innerHTML = [
    `<span class="chip">${tr('Демонов','Daemons')} <b>${daemons.length}${daemons.length !== allDaemons.length ? ` / ${allDaemons.length}` : ''}</b></span>`,
    chip(['generating', 'rework'], tr("пишут код","coding"), STAGE.generating.color),
    chip(['reviewing'], tr("ревью","reviewing"), STAGE.reviewing.color),
    chip(['exploring'], tr("изучают бэклог","exploring backlog"), STAGE.exploring.color),
    chip(['git', 'jenkins', 'jira', 'success'], tr("пост-обработка","delivering"), STAGE.jenkins.color),
    chip(['idle', 'polling', 'starting'], tr("ждут","idle"), STAGE.idle.color),
    chip(['error'], tr("ошибки","errors"), STAGE.error.color),
    chip(['lost'], tr("нет сигнала","no signal"), STAGE.lost.color),
  ].join('');
}

function buildLegend() {
  const items = ['generating', 'reviewing', 'git', 'jenkins', 'jira', 'exploring', 'retro', 'success', 'error', 'idle', 'lost'];
  $('legend').innerHTML = items.map((k) => `<span><i class="dot" style="background:${STAGE[k].color}"></i>${STAGE[k].label}</span>`).join('');
}

// ------------------------------------------------------------------ «проверь Jira сейчас»
// Двойной клик по демону: он идёт к доске задач, а сам демон опрашивает Jira, не дожидаясь конца ожидания
async function pokeDemon(id) {
  const w = office.workers.get(id), t = office.t;
  let res = { ok: false, reason: 'network' };
  try { res = await (await fetch('/api/poke', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }) })).json(); } catch { /* сервер недоступен */ }
  if (!w) return res;
  if (res.ok) {
    if (w.plan) w.endPlan(t, true);
    w.startPlan('poke', [{ place: { key: 'board', pos: BOARD[w.slot % BOARD.length], node: 'board', face: 'up', act: 'think' },
      dur: 6, say: pick([tr("Проверю Jira!","Checking Jira!"), tr("Сейчас гляну задачи","Let me check the tasks"), tr("Есть что-нибудь новое?","Anything new?"), tr("Бегу смотреть Jira","Off to check Jira")]) }], t);
  } else {
    const why = { busy: `${tr('Занят','Busy')}: ${(STAGE[res.stage] || STAGE.idle).label.toLowerCase()}`, old: tr("Не умею — обнови скрипт демона","Update the daemon to enable this"),
      offline: '…', unknown: '?', network: tr("Нет связи с сервером","Cannot reach the server"), readonly: tr("Дашборд только для просмотра","Dashboard is read-only") }[res.reason] || tr("Не получилось","Could not complete the action");
    w.sayLine(why, t, 2.6);
    if (w.mode === 'stand') w.shot('think', t);
  }
  return res;
}
