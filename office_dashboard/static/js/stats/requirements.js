'use strict';
const requirementStatus = {queued:tr('В очереди', 'Queued'), running:tr('В работе', 'Running'), blocked:tr('Ждёт уточнения в Jira', 'Awaiting clarification in Jira'), done:tr('Завершена', 'Completed'), failed:tr('Не завершена', 'Not completed'), interrupted:tr('Прервана', 'Interrupted'), cancelled:tr('Отменена', 'Cancelled')};
let requirementsData = null;
function drawRequirements(data) {
  requirementsData = data;
  const query = $('workspaceSearch').value.trim().toLowerCase();
  const rows = data.rows.filter(r => [r.issue,r.id,demonName(r.id),r.note].join(' ').toLowerCase().includes(query));
  const page = sectionPage('workspace-requirements:requests', rows, workspacePaginationKey(), tr('Переделки по новой постановке', 'Requirements rework'));
  const done = rows.filter(r=>r.status==='done'), seconds = rows.reduce((s,r)=>s+(r.total_seconds||0),0);
  workspaceRender(`<div class="kpis">${metric(tr('Запросов', 'Requests'),rows.length)}${metric(tr('Завершено', 'Completed'),done.length)}${metric(tr('В очереди / в работе', 'Queued / running'),rows.filter(r=>r.status==='queued').length+' / '+rows.filter(r=>r.status==='running').length)}${metric(tr('Требуют внимания', 'Need attention'),rows.filter(r=>['failed','interrupted','blocked'].includes(r.status)).length,tr('Ошибки, вопросы и прерванные запросы', 'Errors, questions, and interrupted requests'))}${metric(tr('Время переделок', 'Rework time'),minutes(seconds))}${metric(tr('Токены', 'Tokens'),rows.reduce((s,r)=>s+(r.tokens?.total||0),0).toLocaleString(uiLocale()),`${tr("Данные есть у ", "Data available for ")}${rows.filter(r=>r.tokens?.total).length}${tr(" запросов", " requests")}`)}</div>
    <div class="workspace-actions">${data.control ? tr('<button class="btn primary" data-new-requirements>Новая переделка</button><span class="muted">Демон перечитает актуальную задачу в Jira</span>', '<button class="btn primary" data-new-requirements>New rework request</button><span class="muted">The daemon will reread the current Jira task</span>') : tr('<p class="muted">Для новых запросов включите управление в основном дашборде.</p>', '<p class="muted">Enable controls in the main dashboard to create requests.</p>')}</div><div id="requirementsForm"></div>` +
    (rows.length ? workspaceTable([tr('Задача / демон', 'Task / daemon'),tr('Новая постановка', 'New requirements'),tr('Состояние', 'Status'),tr('Время / токены', 'Time / tokens'),tr('Результат', 'Result')],page.rows.map(r=>`<tr><td><strong>${esc(r.issue)}</strong><br>${esc(r.id)}<br><time class="muted">${esc(new Date(r.created_at*1000).toLocaleString(uiLocale()))}</time></td><td class="requirements-note">${esc(r.note)}</td><td><span class="state-label state-${esc(r.status)}">${esc(r.waiting_reason ? tr('Ожидает зависимости', 'Waiting for a dependency') : requirementStatus[r.status]||r.status)}</span>${data.control && ['queued','blocked'].includes(r.status) ? `<div class="row-action" data-cancel-container><button class="btn" data-cancel-requirements="${esc(r.request)}" data-daemon="${esc(r.id)}">${tr("Отменить запрос", "Cancel request")}</button></div>` : ''}</td><td>${minutes(r.total_seconds)}<br><span class="muted">${r.tokens?.total == null ? tr('Расход не известен', 'Usage unknown') : esc(r.tokens.total.toLocaleString(uiLocale()))+tr(' токенов', ' tokens')}</span></td><td>${esc(translateServerMessage(r.waiting_reason||r.error||''))}<details data-detail="${esc(r.request)}"><summary>${tr("Ветка и требования", "Branch and requirements")}</summary><p>${esc(r.branch||tr('Ветка пока не создана', 'No branch created yet'))}</p><code>${esc(r.requirements_hash||tr('Версия требований пока не получена', 'Requirements version not received yet'))}</code></details>${data.control && ['failed','interrupted','done','blocked'].includes(r.status) ? `<button class="btn" data-again-requirements="${esc(r.request)}">${tr("Повторить новым запросом", "Repeat as a new request")}</button>` : ''}</td></tr>`)) + page.footer:
      workspaceEmpty(query ? tr('Запросы не найдены', 'No requests found') : tr('Переделок пока нет', 'No rework requests yet'), query ? tr('Измените поисковый запрос или фильтры.', 'Change the search or filters.') : tr('Если аналитик изменил постановку, создайте запрос. Переделки учитываются отдельно от обычных задач и замечаний к PR.', 'Create a request when an analyst changes the requirements. Rework is tracked separately from ordinary tasks and PR feedback.'))));
  if (workspace.requirementsDaemon) { const id=workspace.requirementsDaemon; workspace.requirementsDaemon=null; openRequirementsForm(id); }
}
async function openRequirementsForm(id='', previous=null) {
  if (workspace.view !== 'requirements') return;
  if (workspaceEditing()) { $('requirementsForm')?.querySelector('input')?.focus(); return; }
  if (!$('requirementsForm')) { await loadWorkspace(); if (!$('requirementsForm')) return; }
  if (!requirementsData?.control) return;
  const serial = ++workspace.serial;
  $('workspaceStatus').textContent = tr('Загрузка списка демонов…', 'Loading daemons…');
  let state;
  try { state = await workspaceJson('/api/state'); }
  catch (e) { $('workspaceStatus').textContent = translateServerMessage(e.message); return; }
  if (workspace.view !== 'requirements' || serial !== workspace.serial || !$('requirementsForm')) return;
  if (!state.daemons?.length) {
    $('workspaceStatus').textContent = tr('Нет доступных демонов. Сначала добавьте и запустите демона.', 'No daemons available. Add and start a daemon first.'); return;
  }
  $('requirementsForm').innerHTML = `<form class="memory-approval requirements-editor"><div class="editor-heading"><h3>${tr("Новая переделка", "New rework request")}</h3><span class="muted">${tr("Отдельная ветка и отдельный учёт", "A separate branch and separate tracking")}</span></div><div class="form-grid"><label>${tr("Демон", "Daemon")}<select name="id" required>${state.daemons.map(d=>`<option value="${esc(d.id)}">${esc(daemonOptionName(d))}</option>`).join('')}</select></label><label>${tr("Ключ задачи Jira", "Jira issue key")}<input name="issue" required pattern="[A-Za-z][A-Za-z0-9_]*-[0-9]+" maxlength="100" placeholder="PROJECT-123" autocomplete="off" title="${tr("Ключ проекта и номер задачи, например PROJECT-123", "Project key and issue number, for example PROJECT-123")}"></label></div><label>${tr("Что изменилось в постановке", "What changed in the requirements")}<textarea name="note" required maxlength="2000" placeholder="${tr("Например: изменились правила расчёта. Новое описание уже в Jira.", "For example: calculation rules changed. The updated description is already in Jira.")}"></textarea></label><p class="form-hint">${tr("Демон прочитает актуальную постановку в Jira и создаст отдельную ветку от предыдущей работы, а после её слияния — от базовой ветки. Прежний PR сохранится.", "The daemon reads the current Jira requirements and creates a separate branch from the previous work, or from the base branch once that work is merged. The existing PR is preserved.")}</p><div class="form-actions"><button class="btn primary" type="submit">${tr("Поставить в очередь", "Add to queue")}</button><button class="btn" type="button" data-close-requirements>${tr("Отмена", "Cancel")}</button></div><p role="status" class="form-status"></p></form>`;
  const form=$('requirementsForm').querySelector('form');
  if (id && state.daemons.some(d=>d.id===id)) form.elements.id.value=id;
  if (previous) {form.elements.issue.value=previous.issue; form.elements.note.value=previous.note;}
  form.onsubmit=async e=>{
    e.preventDefault();
    const buttons = [...form.querySelectorAll('button')]; buttons.forEach(b=>b.disabled=true);
    form.querySelector('[role=status]').textContent=tr('Сохранение запроса…', 'Saving request…');
    try {
      await requirementsAction({action:'submit',id:form.elements.id.value,issue:form.elements.issue.value.trim().toUpperCase(),note:form.elements.note.value.trim()});
      markFormClean(form);
      delete workspace.cache.requirements;
      if (workspace.view === 'requirements' && form.isConnected) {
        form.remove(); workspaceEditorState();
        const refreshed = await loadWorkspace(true);
        $('workspaceStatus').textContent = refreshed ? tr('Переделка добавлена в очередь.', 'Rework added to the queue.') : tr('Переделка добавлена в очередь. ', 'Rework added to the queue. ') + $('workspaceStatus').textContent + tr(' Нажмите «Обновить», чтобы увидеть очередь.', ' Select Refresh to see the queue.');
      }
    } catch(e) {form.querySelector('[role=status]').textContent=translateServerMessage(e.message); buttons.forEach(b=>b.disabled=false);}
  };
  workspaceEditorState(); form.elements.issue.focus();
}
async function requirementsAction(body) {
  const result=await workspaceJson('/api/requirements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!result.ok) throw Error(translateServerMessage(result.reason||tr('Запрос не сохранён', 'Request was not saved')));
}
$('workspaceBody').addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-new-requirements')) return openRequirementsForm();
  if(b.hasAttribute('data-close-requirements')) { markFormClean($('requirementsForm')); $('requirementsForm').textContent=''; workspaceEditorState(); $('workspaceStatus').textContent=tr('Создание переделки отменено.', 'Rework request creation cancelled.'); return; }
  if(b.dataset.againRequirements) {
    const r=requirementsData.rows.find(r=>r.request===b.dataset.againRequirements); if (r) return openRequirementsForm(r.id,r);
  }
  if(b.dataset.cancelRequirements) {
    if (workspaceEditing()) return;
    const container = b.closest('[data-cancel-container]'), daemon=b.dataset.daemon, request=b.dataset.cancelRequirements;
    container.innerHTML=tr('<form class="requirement-cancel"><p>Убрать запрос из очереди? Демон не начнёт эту переделку.</p><div class="form-actions"><button class="btn" type="submit">Да, отменить</button><button class="btn" type="button" data-keep-requirements>Оставить</button></div><p role="status"></p></form>', '<form class="requirement-cancel"><p>Remove this request from the queue? The daemon will not start this rework.</p><div class="form-actions"><button class="btn" type="submit">Yes, cancel</button><button class="btn" type="button" data-keep-requirements>Keep</button></div><p role="status"></p></form>');
    const form=container.querySelector('form'); workspaceEditorState(); form.querySelector('button').focus();
    form.onsubmit=async event=>{
      event.preventDefault(); [...form.querySelectorAll('button')].forEach(button=>button.disabled=true);
      try {
        await requirementsAction({action:'cancel',id:daemon,request});
        markFormClean(form);
        delete workspace.cache.requirements;
        if (workspace.view === 'requirements' && form.isConnected) {
          container.textContent = tr('Запрос отменён.', 'Request cancelled.'); workspaceEditorState();
          const refreshed = await loadWorkspace(true);
          $('workspaceStatus').textContent = refreshed ? tr('Запрос отменён.', 'Request cancelled.') : tr('Запрос отменён. ', 'Request cancelled. ') + $('workspaceStatus').textContent + tr(' Нажмите «Обновить», чтобы увидеть очередь.', ' Select Refresh to see the queue.');
        }
      } catch(error) {form.querySelector('[role=status]').textContent=translateServerMessage(error.message); [...form.querySelectorAll('button')].forEach(button=>button.disabled=false);}
    };
  }
  if(b.hasAttribute('data-keep-requirements')) { markFormClean(b.closest('form')); drawRequirements(requirementsData); $('workspaceStatus').textContent=tr('Запрос остался в очереди.', 'Request remains in the queue.'); }
});
