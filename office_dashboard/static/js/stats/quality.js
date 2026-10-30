'use strict';
/*
 * «Что стало со сданными задачами» во вкладке «Статистика»: слито без правок, правили люди, брошено.
 * Данные — /api/quality (logs/*-delivered.jsonl + *-outcomes.json, их пишет ретроспектива демона).
 * Ретроспектива смотрит задачи спустя несколько дней, поэтому для коротких периодов («Сегодня»,
 * «7 дней») раздел показывает последние 12 недель.
 */

const OUTCOME = {
  as_is:   { label: tr('Без правок', 'No changes'),    icon: '✓', color: 'var(--st-good)' },
  changed: { label: tr('Правили люди', 'Edited by people'),  icon: '✎', color: 'var(--st-warn)' },
  dropped: { label: tr('Без слияния', 'Not merged'),       icon: '✗', color: 'var(--st-crit)' },
};
const QUALITY_KEYS = ['as_is', 'changed', 'dropped'];
const quality = { key: null, data: null, loading: false, error: '' };

function qualityDays() {
  if (stats.period === '30') return 30;
  if (stats.period === 'all') return 0;
  return 84;   // сегодня / 7 дней — у ретроспективы ещё нет данных, берём 12 недель
}

async function loadQuality() {
  const key = `${qualityDays()}|${stats.demon}|${stats.room}`;
  if (quality.loading) return;
  quality.loading = true; quality.error = '';
  try {
    const q = new URLSearchParams({ days: String(qualityDays()), id: stats.demon, office: stats.room });
    quality.data = await workspaceJson(`/api/quality?${q}`);
    quality.key = key;
  } catch (e) {
    quality.data = null; quality.error = translateServerMessage(e.message); quality.key = key;
  } finally {
    quality.loading = false;
  }
  if (key !== `${qualityDays()}|${stats.demon}|${stats.room}`) { renderQuality(); return; }
  drawQuality();
}

// Вызывается из renderStats: рисует, что есть, и при смене периода/демона перезапрашивает
function renderQuality() {
  const key = `${qualityDays()}|${stats.demon}|${stats.room}`;
  if (quality.key !== key || (!quality.data && !quality.error)) loadQuality();
  drawQuality();
}

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const share = (c) => (c.resolved ? c.as_is / c.resolved : null);

function drawQuality() {
  const card = $('qualityCard');
  if (!card) return;
  const d = quality.key === `${qualityDays()}|${stats.demon}|${stats.room}` ? quality.data : null;
  const period = qualityDays() === 84 && (stats.period === 'today' || stats.period === '7') ? tr(' · последние 12 недель', ' · last 12 weeks') : '';
  const head = `<h3>${tr("Что стало со сданными задачами ", "Delivered task outcomes ")}<span class="muted">${tr("по офису и демону", "by office and daemon")}${period}${
    d && d.last_check ? `${tr(" · проверено ", " · checked ")}${fmtWhen(d.last_check)}` : ''}</span></h3>`;
  if (!d) {
    card.innerHTML = head + (quality.error ? `<p role="status">${tr("Не удалось загрузить исходы: ", "Could not load outcomes: ")}${esc(quality.error)}</p><button class="btn" data-retry-quality>${tr("Повторить", "Retry")}</button>` : tr('<div class="workspace-loading compact" aria-label="Загрузка исходов"><span></span><span></span></div>', '<div class="workspace-loading compact" aria-label="Loading outcomes"><span></span><span></span></div>'));
    card.querySelector('[data-retry-quality]')?.addEventListener('click', ()=>{quality.error=''; loadQuality(); drawQuality();}); return;
  }
  const t = d.totals;
  if (!t.total) {
    card.innerHTML = head + workspaceEmpty(tr('Исходов за этот период пока нет', 'No outcomes for this period yet'), tr('После сдачи задачи демон проверит историю Git и покажет, была ли работа слита и потребовались ли правки.', 'After delivery, the daemon checks Git history to show whether the work was merged and whether further changes were needed.'));
    return;
  }
  const tile = (label, value, sub, o) => `<div class="kpi">${o ? `<div class="kpi-label"><i class="sw" style="background:${o.color}"></i>${o.icon} ${label}</div>`
    : `<div class="kpi-label">${label}</div>`}<div class="kpi-value">${value}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
  const waiting = t.open + t.waiting + t.unknown;
  const resolvedSub = t.resolved ? `${t.as_is}${tr(" из ", " of ")}${t.resolved}${tr(" задач с исходом", " tasks with an outcome")}` : tr('исходов пока нет', 'no outcomes yet');
  card.innerHTML = head + `
    <div class="kpis">
      ${tile(tr('Слито без правок', 'Merged unchanged'), pct(t.as_is_share), resolvedSub, OUTCOME.as_is)}
      ${tile(tr('Правили люди', 'Edited by people'), t.changed, t.changed ? `≈ ${t.human_lines}${tr(" строк изменено", " lines changed")}` : tr('ручные правки не зафиксированы', 'no human edits recorded'), OUTCOME.changed)}
      ${tile(tr('Без слияния', 'Not merged'), t.dropped, tr('ветку удалили без слияния', 'branch deleted without merging'), OUTCOME.dropped)}
      ${tile(tr('Доработки после слияния', 'Post-merge fixes'), t.followups, tr('задач с коммитами-исправлениями в базе', 'tasks with follow-up commits in the base branch'))}
      ${tile(tr('Ждут исхода', 'Awaiting outcome'), waiting, [t.open ? `${t.open}${tr(" ещё не слиты", " not merged yet")}` : '', t.waiting ? `${t.waiting}${tr(" не проверялись", " not checked yet")}` : '',
        t.unknown ? `${t.unknown}${tr(" без коммита", " without a commit")}` : ''].filter(Boolean).join(' · ') || tr('все проверены', 'all checked'))}
    </div>
    <div class="chart-row">
      <figure class="chart-card"><figcaption>${tr("Исход по неделям сдачи", "Outcomes by delivery week")}</figcaption>
        <div class="legend-row">${QUALITY_KEYS.map((k) => `<span><i class="sw" style="background:${OUTCOME[k].color}"></i>${OUTCOME[k].icon} ${OUTCOME[k].label}</span>`).join('')}</div>
        <div class="chart" id="chQuality"></div></figure>
      <figure class="chart-card"><figcaption>${tr("Доля «без правок» по неделям", "Unchanged share by week")}</figcaption>
        <div class="chart" id="chQualityShare"></div></figure>
    </div>
    ${qualityTable(d.by_daemon)}`;
  drawQualityWeeks($('chQuality'), d.weeks);
  drawQualityShare($('chQualityShare'), d.weeks);
  enhanceDataTables(card);
}

function weekLabel(ts) {
  const a = new Date(ts * 1000), b = new Date((ts + 6 * 86400) * 1000);
  return `${a.toLocaleDateString(uiLocale(), {day:'2-digit', month:'2-digit'})}–${b.toLocaleDateString(uiLocale(), {day:'2-digit', month:'2-digit'})}`;
}
function weekTip(w) {
  const rows = QUALITY_KEYS.map((k) => `<div><i class="sw" style="background:${OUTCOME[k].color}"></i>${OUTCOME[k].icon} ${OUTCOME[k].label}: <b>${w[k]}</b></div>`).join('');
  const rest = w.open + w.waiting + w.unknown;
  return `<b>${tr("Неделя ", "Week ")}${weekLabel(w.start)}</b><div>${tr("Сдано задач: ", "Tasks delivered: ")}<b>${w.total}</b></div>${rows}
    ${rest ? `<div class="muted">${tr("ждут исхода: ", "awaiting outcome: ")}${rest}</div>` : ''}<div>${tr("Без правок: ", "No changes: ")}<b>${pct(share(w))}</b></div>`;
}

// Столбики по неделям: без правок / правили / брошено (ожидающие исхода не рисуются — они в подсказке)
function drawQualityWeeks(el, weeks) {
  const W = el.clientWidth || 560, H = 200, L = 30, R = 8, T = 10, B = 26;
  const n = Math.max(1, weeks.length), max = niceMax(Math.max(1, ...weeks.map((w) => w.resolved)));
  const band = (W - L - R) / n, bw = Math.min(28, Math.max(4, band * 0.62));
  const y = (v) => T + (H - T - B) * (1 - v / max);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${tr("Исход сданных задач по неделям", "Delivered task outcomes by week")}">`;
  for (const v of [0, max / 2, max].filter((v, i, a) => a.indexOf(v) === i && Number.isInteger(v))) {
    svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${L - 6}" y="${y(v) + 4}" class="axis" text-anchor="end">${v}</text>`;
  }
  const labelEvery = Math.ceil(n / Math.max(1, Math.floor((W - L - R) / 52)));
  weeks.forEach((w, i) => {
    const x = L + i * band + (band - bw) / 2;
    const segs = QUALITY_KEYS.filter((k) => w[k] > 0);
    let acc = 0;
    segs.forEach((k, si) => {
      const y0 = y(acc), y1 = y(acc + w[k]), gap = si > 0 ? 2 : 0, h = Math.max(0, y0 - y1 - gap);
      svg += si === segs.length - 1 ? `<path d="${roundTop(x, y1, bw, h, Math.min(4, h, bw / 2))}" fill="${OUTCOME[k].color}"/>`
        : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" fill="${OUTCOME[k].color}"/>`;
      acc += w[k];
    });
    if (i % labelEvery === 0 || i === n - 1) {
      const d = new Date(w.start * 1000);
      svg += `<text x="${x + bw / 2}" y="${H - 8}" class="axis" text-anchor="middle">${d.toLocaleDateString(uiLocale(), {day:'2-digit', month:'2-digit'})}</text>`;
    }
    svg += `<rect x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}" class="hit" data-i="${i}"/>`;
  });
  svg += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" class="base"/></svg>`;
  el.innerHTML = svg;
  bindWeekTips(el, weeks);
}

// Линия доли «без правок»: учится ли демон. Точки — недели, где был хоть один исход
function drawQualityShare(el, weeks) {
  const W = el.clientWidth || 420, H = 200, L = 38, R = 14, T = 12, B = 26;
  const n = Math.max(1, weeks.length), band = (W - L - R) / n;
  const x = (i) => L + band * (i + 0.5), y = (v) => T + (H - T - B) * (1 - v);
  const pts = weeks.map((w, i) => ({ i, v: share(w) })).filter((p) => p.v != null);
  let svg = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${tr("Доля задач без правок по неделям", "Share of unchanged tasks by week")}">`;
  for (const v of [0, 0.5, 1]) svg += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/><text x="${L - 6}" y="${y(v) + 4}" class="axis" text-anchor="end">${v * 100}%</text>`;
  if (pts.length) {
    svg += `<path d="${pts.map((p, k) => `${k ? 'L' : 'M'}${x(p.i)},${y(p.v)}`).join('')}" fill="none" stroke="var(--st-good)" stroke-width="2" stroke-linejoin="round"/>`;
    for (const p of pts) svg += `<circle cx="${x(p.i)}" cy="${y(p.v)}" r="4" fill="var(--st-good)" stroke="var(--card)" stroke-width="2"/>`;
    const last = pts[pts.length - 1];
    // Подпись только у последней точки — над ней, не залезая на линию
    svg += `<text x="${Math.min(x(last.i), W - R - 16)}" y="${Math.max(T + 10, y(last.v) - 12)}" class="value" text-anchor="middle">${pct(last.v)}</text>`;
  } else {
    svg += `<text x="${W / 2}" y="${H / 2}" class="axis" text-anchor="middle">${tr("исходов пока нет", "no outcomes yet")}</text>`;
  }
  const labelEvery = Math.ceil(n / Math.max(1, Math.floor((W - L - R) / 52)));
  weeks.forEach((w, i) => {
    if (i % labelEvery === 0 || i === n - 1) {
      const d = new Date(w.start * 1000);
      svg += `<text x="${x(i)}" y="${H - 8}" class="axis" text-anchor="middle">${d.toLocaleDateString(uiLocale(), {day:'2-digit', month:'2-digit'})}</text>`;
    }
    svg += `<rect x="${L + i * band}" y="${T}" width="${band}" height="${H - T - B}" class="hit" data-i="${i}"/>`;
  });
  el.innerHTML = svg + `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" class="base"/></svg>`;
  bindWeekTips(el, weeks);
}

function bindWeekTips(el, weeks) {
  el.querySelectorAll('.hit').forEach((h) => {
    h.addEventListener('mousemove', (e) => showTip(e, weekTip(weeks[+h.dataset.i])));
    h.addEventListener('mouseleave', hideTip);
  });
}

function qualityTable(rows) {
  // Сервисы одного демона — рядом: сначала демоны по числу сданных задач, внутри — сервисы
  const byDemon = {};
  for (const r of rows) byDemon[r.id] = (byDemon[r.id] || 0) + r.total;
  const sorted = [...rows].sort((a, b) => byDemon[b.id] - byDemon[a.id] || a.id.localeCompare(b.id, uiLocale()) ||
    String(a.service || '').localeCompare(String(b.service || ''), uiLocale()));
  const page = sectionPage('stats:quality', sorted, statsPaginationKey(), tr('Исходы по демонам', 'Outcomes by daemon'));
  return `<div class="table-wrap"><table class="tbl"><thead><tr><th>${tr("Демон", "Daemon")}</th><th>${tr("Сервис", "Service")}</th><th class="num">${tr("Сдано", "Delivered")}</th>
    <th class="num">${OUTCOME.as_is.icon}${tr(" Без правок", " Unchanged")}</th><th class="num">${OUTCOME.changed.icon}${tr(" Правили", " Edited")}</th>
    <th class="num">${OUTCOME.dropped.icon}${tr(" Брошено", " Abandoned")}</th><th class="num">${tr("Ждут", "Waiting")}</th><th class="num">${tr("Доработки", "Follow-ups")}</th>
    <th class="num">${tr("Доля без правок", "Unchanged share")}</th></tr></thead><tbody>${page.rows.map((r) => `<tr>
      <td>${esc(demonName(r.id))} <span class="muted">${esc(demonKey(r.id))}</span></td>
      <td>${r.service ? `<span class="svc">${esc(r.service)}</span>` : '<span class="muted">—</span>'}</td>
      <td class="num strong">${r.total}</td><td class="num">${r.as_is || ''}</td><td class="num">${r.changed || ''}</td>
      <td class="num">${r.dropped || ''}</td><td class="num">${(r.open + r.waiting + r.unknown) || ''}</td>
      <td class="num">${r.followups || ''}</td><td class="num">${pct(r.as_is_share)}</td></tr>`).join('')}
    </tbody></table></div>${page.footer}`;
}
