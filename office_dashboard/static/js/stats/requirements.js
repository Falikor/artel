'use strict';
const requirementStatus = {queued:'В очереди', running:'В работе', blocked:'Ждёт уточнения в Jira', done:'Завершена', failed:'Не завершена', interrupted:'Прервана', cancelled:'Отменена'};
let requirementsData = null;
function drawRequirements(data) {
  requirementsData = data;
  const query = $('workspaceSearch').value.trim().toLowerCase();
  const rows = data.rows.filter(r => [r.issue,r.id,demonName(r.id),r.note].join(' ').toLowerCase().includes(query));
  const page = sectionPage('workspace-requirements:requests', rows, workspacePaginationKey(), 'Переделки по новой постановке');
  const done = rows.filter(r=>r.status==='done'), seconds = rows.reduce((s,r)=>s+(r.total_seconds||0),0);
  workspaceRender(`<div class="kpis">${metric('Запросов',rows.length)}${metric('Завершено',done.length)}${metric('В очереди / в работе',rows.filter(r=>r.status==='queued').length+' / '+rows.filter(r=>r.status==='running').length)}${metric('Требуют внимания',rows.filter(r=>['failed','interrupted','blocked'].includes(r.status)).length,'Ошибки, вопросы и прерванные запросы')}${metric('Время переделок',minutes(seconds))}${metric('Токены',rows.reduce((s,r)=>s+(r.tokens?.total||0),0).toLocaleString('ru-RU'),`Данные есть у ${rows.filter(r=>r.tokens?.total).length} запросов`)}</div>
    <div class="workspace-actions">${data.control ? '<button class="btn primary" data-new-requirements>Новая переделка</button><span class="muted">Демон перечитает актуальную задачу в Jira</span>' : '<p class="muted">Для новых запросов включите управление в основном дашборде.</p>'}</div><div id="requirementsForm"></div>` +
    (rows.length ? workspaceTable(['Задача / демон','Новая постановка','Состояние','Время / токены','Результат'],page.rows.map(r=>`<tr><td><strong>${esc(r.issue)}</strong><br>${esc(r.id)}<br><time class="muted">${esc(new Date(r.created_at*1000).toLocaleString('ru-RU'))}</time></td><td class="requirements-note">${esc(r.note)}</td><td><span class="state-label state-${esc(r.status)}">${esc(r.waiting_reason ? 'Ожидает зависимости' : requirementStatus[r.status]||r.status)}</span>${data.control && ['queued','blocked'].includes(r.status) ? `<div class="row-action" data-cancel-container><button class="btn" data-cancel-requirements="${esc(r.request)}" data-daemon="${esc(r.id)}">Отменить запрос</button></div>` : ''}</td><td>${minutes(r.total_seconds)}<br><span class="muted">${r.tokens?.total == null ? 'Расход не известен' : esc(r.tokens.total.toLocaleString('ru-RU'))+' токенов'}</span></td><td>${esc(r.waiting_reason||r.error||'')}<details data-detail="${esc(r.request)}"><summary>Ветка и требования</summary><p>${esc(r.branch||'Ветка пока не создана')}</p><code>${esc(r.requirements_hash||'Версия требований пока не получена')}</code></details>${data.control && ['failed','interrupted','done','blocked'].includes(r.status) ? `<button class="btn" data-again-requirements="${esc(r.request)}">Повторить новым запросом</button>` : ''}</td></tr>`)) + page.footer:
      workspaceEmpty(query ? 'Запросы не найдены' : 'Переделок пока нет', query ? 'Измените поисковый запрос или фильтры.' : 'Если аналитик изменил постановку, создайте запрос. Переделки учитываются отдельно от обычных задач и замечаний к PR.')));
  if (workspace.requirementsDaemon) { const id=workspace.requirementsDaemon; workspace.requirementsDaemon=null; openRequirementsForm(id); }
}
async function openRequirementsForm(id='', previous=null) {
  if (workspace.view !== 'requirements') return;
  if (workspaceEditing()) { $('requirementsForm')?.querySelector('input')?.focus(); return; }
  if (!$('requirementsForm')) { await loadWorkspace(); if (!$('requirementsForm')) return; }
  if (!requirementsData?.control) return;
  const serial = ++workspace.serial;
  $('workspaceStatus').textContent = 'Загрузка списка демонов…';
  let state;
  try { state = await workspaceJson('/api/state'); }
  catch (e) { $('workspaceStatus').textContent = e.message; return; }
  if (workspace.view !== 'requirements' || serial !== workspace.serial || !$('requirementsForm')) return;
  if (!state.daemons?.length) {
    $('workspaceStatus').textContent = 'Нет доступных демонов. Сначала добавьте и запустите демона.'; return;
  }
  $('requirementsForm').innerHTML = `<form class="memory-approval requirements-editor"><div class="editor-heading"><h3>Новая переделка</h3><span class="muted">Отдельная ветка и отдельный учёт</span></div><div class="form-grid"><label>Демон<select name="id" required>${state.daemons.map(d=>`<option value="${esc(d.id)}">${esc(daemonOptionName(d))}</option>`).join('')}</select></label><label>Ключ задачи Jira<input name="issue" required pattern="[A-Za-z][A-Za-z0-9_]*-[0-9]+" maxlength="100" placeholder="PROJECT-123" autocomplete="off" title="Ключ проекта и номер задачи, например PROJECT-123"></label></div><label>Что изменилось в постановке<textarea name="note" required maxlength="2000" placeholder="Например: изменились правила расчёта. Новое описание уже в Jira."></textarea></label><p class="form-hint">Демон прочитает актуальную постановку в Jira и создаст отдельную ветку от предыдущей работы, а после её слияния — от базовой ветки. Прежний PR сохранится.</p><div class="form-actions"><button class="btn primary" type="submit">Поставить в очередь</button><button class="btn" type="button" data-close-requirements>Отмена</button></div><p role="status" class="form-status"></p></form>`;
  const form=$('requirementsForm').querySelector('form');
  if (id && state.daemons.some(d=>d.id===id)) form.elements.id.value=id;
  if (previous) {form.elements.issue.value=previous.issue; form.elements.note.value=previous.note;}
  form.onsubmit=async e=>{
    e.preventDefault();
    const buttons = [...form.querySelectorAll('button')]; buttons.forEach(b=>b.disabled=true);
    form.querySelector('[role=status]').textContent='Сохранение запроса…';
    try {
      await requirementsAction({action:'submit',id:form.elements.id.value,issue:form.elements.issue.value.trim().toUpperCase(),note:form.elements.note.value.trim()});
      delete workspace.cache.requirements;
      if (workspace.view === 'requirements' && form.isConnected) {
        form.remove(); workspaceEditorState();
        const refreshed = await loadWorkspace(true);
        $('workspaceStatus').textContent = refreshed ? 'Переделка добавлена в очередь.' : 'Переделка добавлена в очередь. ' + $('workspaceStatus').textContent + ' Нажмите «Обновить», чтобы увидеть очередь.';
      }
    } catch(e) {form.querySelector('[role=status]').textContent=e.message; buttons.forEach(b=>b.disabled=false);}
  };
  workspaceEditorState(); form.elements.issue.focus();
}
async function requirementsAction(body) {
  const result=await workspaceJson('/api/requirements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!result.ok) throw Error(result.reason||'Запрос не сохранён');
}
$('workspaceBody').addEventListener('click',async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-new-requirements')) return openRequirementsForm();
  if(b.hasAttribute('data-close-requirements')) { $('requirementsForm').textContent=''; workspaceEditorState(); $('workspaceStatus').textContent='Создание переделки отменено.'; return; }
  if(b.dataset.againRequirements) {
    const r=requirementsData.rows.find(r=>r.request===b.dataset.againRequirements); if (r) return openRequirementsForm(r.id,r);
  }
  if(b.dataset.cancelRequirements) {
    if (workspaceEditing()) return;
    const container = b.closest('[data-cancel-container]'), daemon=b.dataset.daemon, request=b.dataset.cancelRequirements;
    container.innerHTML='<form class="requirement-cancel"><p>Убрать запрос из очереди? Демон не начнёт эту переделку.</p><div class="form-actions"><button class="btn" type="submit">Да, отменить</button><button class="btn" type="button" data-keep-requirements>Оставить</button></div><p role="status"></p></form>';
    const form=container.querySelector('form'); workspaceEditorState(); form.querySelector('button').focus();
    form.onsubmit=async event=>{
      event.preventDefault(); [...form.querySelectorAll('button')].forEach(button=>button.disabled=true);
      try {
        await requirementsAction({action:'cancel',id:daemon,request});
        delete workspace.cache.requirements;
        if (workspace.view === 'requirements' && form.isConnected) {
          container.textContent = 'Запрос отменён.'; workspaceEditorState();
          const refreshed = await loadWorkspace(true);
          $('workspaceStatus').textContent = refreshed ? 'Запрос отменён.' : 'Запрос отменён. ' + $('workspaceStatus').textContent + ' Нажмите «Обновить», чтобы увидеть очередь.';
        }
      } catch(error) {form.querySelector('[role=status]').textContent=error.message; [...form.querySelectorAll('button')].forEach(button=>button.disabled=false);}
    };
  }
  if(b.hasAttribute('data-keep-requirements')) { drawRequirements(requirementsData); $('workspaceStatus').textContent='Запрос остался в очереди.'; }
});
