'use strict';
/*
 * Предложения в простое во вкладке «Статистика»: демон изучил задачу из бэклога (OpenSpec explore)
 * и оставил в ней комментарий с предложениями. Данные — proposals из /api/history
 * (logs/*-proposals.jsonl: строка на каждый прогон исследования, с токенами).
 */

const PROPOSAL = {
  posted:     { label: tr('Предложения оставлены', 'Suggestions posted'), icon: '✓', color: 'var(--st-good)' },
  not_posted: { label: tr('Не удалось оставить', 'Could not post'),   icon: '✗', color: 'var(--st-crit)' },
  empty:      { label: tr('Без результата', 'No result'),        icon: '—', color: 'var(--muted)' },
  timeout:    { label: tr('Таймаут', 'Timed out'),               icon: '⏱', color: 'var(--st-warn)' },
};

function proposalsTile(props, tile) {
  const posted = props.filter((p) => p.result === 'posted');
  const issues = new Set(posted.map((p) => `${p.id}|${p.issue}`)).size;
  const other = props.length - posted.length;
  const sub = props.length
    ? [`${tr("по ", "across ")}${issues}${tr(" задачам бэклога", " backlog tasks")}`, other ? `${other}${tr(" без комментария", " without a comment")}` : ''].filter(Boolean).join(' · ')
    : tr('демоны не исследовали бэклог', 'no backlog research yet');
  return tile(tr('Предложений в простое', 'Idle suggestions'), posted.length, sub);
}

function proposalLink(p) {
  const base = stats.data && stats.data.daemons[p.id] && stats.data.daemons[p.id].jira_url;
  if (!base) return esc(p.issue);
  const comment = p.comment_id ? `?focusedCommentId=${encodeURIComponent(p.comment_id)}#comment-${encodeURIComponent(p.comment_id)}` : '';
  return `<a href="${esc(base)}/browse/${encodeURIComponent(p.issue)}${comment}" target="_blank" rel="noopener"
    title="${p.comment_id ? tr('открыть комментарий с предложениями', 'open the suggestion comment') : tr('открыть задачу', 'open task')}">${esc(p.issue)}</a>`;
}

function renderProposals(props) {
  const page = sectionPage('stats:proposals', props, statsPaginationKey(), tr('Предложения в простое', 'Idle suggestions'));
  if (!props.length) return '';
  const rows = page.rows;
  return `<section class="table-card"><h3>${tr("Предложения в простое ", "Idle suggestions ")}<span class="muted">${props.length}${tr(" · исследование задач из бэклога", " · backlog research")}</span></h3>
    <div class="table-wrap"><table class="tbl"><thead><tr><th>${tr("Когда", "When")}</th><th>${tr("Демон", "Daemon")}</th><th>${tr("Задача", "Task")}</th><th>${tr("Что в задаче", "Task summary")}</th>
      <th>${tr("Итог", "Outcome")}</th><th class="num">${tr("Время", "Time")}</th><th class="num">${tr("Токены", "Tokens")}</th><th class="num">${tr("Стоимость", "Cost")}</th></tr></thead><tbody>
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
