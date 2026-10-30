'use strict';
/*
 * Предложения в простое во вкладке «Статистика»: демон изучил задачу из бэклога (OpenSpec explore)
 * и оставил в ней комментарий с предложениями. Данные — proposals из /api/history
 * (logs/*-proposals.jsonl: строка на каждый прогон исследования, с токенами).
 */

const PROPOSAL = {
  posted:     { label: 'Предложения оставлены', icon: '✓', color: 'var(--st-good)' },
  not_posted: { label: 'Не удалось оставить',   icon: '✗', color: 'var(--st-crit)' },
  empty:      { label: 'Без результата',        icon: '—', color: 'var(--muted)' },
  timeout:    { label: 'Таймаут',               icon: '⏱', color: 'var(--st-warn)' },
};

function proposalsTile(props, tile) {
  const posted = props.filter((p) => p.result === 'posted');
  const issues = new Set(posted.map((p) => `${p.id}|${p.issue}`)).size;
  const other = props.length - posted.length;
  const sub = props.length
    ? [`по ${issues} задачам бэклога`, other ? `${other} без комментария` : ''].filter(Boolean).join(' · ')
    : 'демоны не исследовали бэклог';
  return tile('Предложений в простое', posted.length, sub);
}

function proposalLink(p) {
  const base = stats.data && stats.data.daemons[p.id] && stats.data.daemons[p.id].jira_url;
  if (!base) return esc(p.issue);
  const comment = p.comment_id ? `?focusedCommentId=${encodeURIComponent(p.comment_id)}#comment-${encodeURIComponent(p.comment_id)}` : '';
  return `<a href="${esc(base)}/browse/${encodeURIComponent(p.issue)}${comment}" target="_blank" rel="noopener"
    title="${p.comment_id ? 'открыть комментарий с предложениями' : 'открыть задачу'}">${esc(p.issue)}</a>`;
}

function renderProposals(props) {
  const page = sectionPage('stats:proposals', props, statsPaginationKey(), 'Предложения в простое');
  if (!props.length) return '';
  const rows = page.rows;
  return `<section class="table-card"><h3>Предложения в простое <span class="muted">${props.length} · исследование задач из бэклога</span></h3>
    <div class="table-wrap"><table class="tbl"><thead><tr><th>Когда</th><th>Демон</th><th>Задача</th><th>Что в задаче</th>
      <th>Итог</th><th class="num">Время</th><th class="num">Токены</th><th class="num">Стоимость</th></tr></thead><tbody>
    ${rows.map((p) => { const res = PROPOSAL[p.result] || PROPOSAL.empty; const c = recCost(p); return `<tr>
      <td class="nowrap">${fmtWhen(p.finished_at)}</td><td>${esc(demonName(p.id))}</td>
      <td class="nowrap">${proposalLink(p)}${p.service ? ` <span class="svc">${esc(p.service)}</span>` : ''}</td>
      <td class="msg" title="${esc(p.summary || '')}">${esc(p.summary || '')}</td>
      <td class="nowrap"><i class="sw" style="background:${res.color}"></i>${res.icon} ${res.label}</td>
      <td class="num">${fmtMin(p.seconds)}</td>
      <td class="num">${p.tokens && p.tokens.total ? fmtTokens(p.tokens.total) : '—'}</td>
      <td class="num" title="${esc(costTitle(p.tokens))}">${c ? (c.estimate ? '≈ ' : '') + fmtMoney(c.value) : '—'}</td></tr>`; }).join('')}
    </tbody></table></div>${page.footer}</section>`;
}
