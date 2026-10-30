'use strict';
/* Кнопки «Остановить» / «Запустить» и переименование демона. */

// ------------------------------------------------------------------ остановить / запустить
// «Остановить» — демон прерывает текущую работу (GigaCode, ревью…) и выходит за секунды; прерванная задача
// при следующем запуске начнётся заново. «Запустить» — через супервизор (python3 artel.py start).
function controlButton(d) {
  if (lastSnapshot.control === false || d.source !== 'state') return '';
  if (drawer.control && drawer.control.id === d.id && Date.now() < drawer.control.until) {
    return `<button class="ctl" disabled>${esc(drawer.control.text)}</button>`;
  }
  if (d.alive) return `<button data-stop="${esc(d.id)}" class="ctl stop" title="${tr('Прервать текущую работу и остановить демона','Interrupt current work and stop the daemon')}">${tr('Остановить','Stop')}</button>`;
  return `<button data-start="${esc(d.id)}" class="ctl start" title="${tr('Запуск через супервизор (artel.py)','Start through the supervisor (artel.py)')}">${tr('Запустить','Start')}</button>`;
}

function stopQuestion(d) {
  const name = displayName(d);
  const busy = { generating: tr("пишет код","writing code"), rework: tr("дорабатывает код","reworking code"), reviewing: tr("проводит ревью","reviewing code"), exploring: tr("изучает задачу","exploring a task"),
    git: tr("пушит ветку","pushing a branch"), jenkins: tr("запускает деплой","starting a deployment"), jira: tr("переводит задачу","updating a Jira status") }[d.stage];
  return busy
    ? tr(`Остановить «${name}»?\n\nСейчас он ${busy}${d.issue ? ' ' + d.issue : ''}. Работа будет прервана, а задача при следующем запуске начнётся заново.`, `Stop “${name}”?\n\nIt is currently ${busy}${d.issue ? ' ' + d.issue : ''}. Work will be interrupted and the task will restart on the next run.`)
    : tr(`Остановить «${name}»?`, `Stop “${name}”?`);
}

async function controlDemon(id, action) {
  let res = { ok: false, reason: 'network' };
  try { res = await (await fetch(`/api/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }) })).json(); } catch { /* сервер недоступен */ }
  const w = office.workers.get(id), t = office.t;
  if (res.ok && w && action === 'stop') w.sayLine(pick([tr("Ухожу…","Signing off…"), tr("Понял, заканчиваю","Understood, wrapping up"), tr("Сохраняюсь и ухожу","Saving and signing off")]), t, 2.6);
  return res;
}

const CONTROL_ERRORS = {
  no_supervisor: tr("Запуск с дашборда — только под супервизором: python3 artel.py start","Dashboard start requires the supervisor: python3 artel.py start"),
  no_config: tr("Неизвестен конфиг демона","Daemon configuration is unknown"), running: tr("Уже работает","Already running"), offline: tr("Демон уже не работает","Daemon is already stopped"),
  old: tr("Демон на другом компьютере и не умеет останавливаться по запросу — обновите его","This remote daemon does not support stop requests. Update it first."),
  readonly: tr("Дашборд запущен только для просмотра (--no-control)","Dashboard is read-only (--no-control)"), network: tr("Нет связи с сервером","Cannot reach the server"),
};

// ------------------------------------------------------------------ имена
async function saveName(id, name) {
  const res = await fetch('/api/names', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, name }) });
  if (!res.ok) throw new Error(tr("не удалось сохранить имя","could not save the name"));
  const names = await res.json();
  for (const d of lastSnapshot.daemons) d.name = names[d.id] || null;  // SSE подтвердит через секунду
  renderCards();
  return names;
}

// Переименование с явным сохранением; ошибки остаются рядом с введённым именем.
function startRename(container, d, done) {
  container.innerHTML = `<form class="rename-form"><label class="sr-only" for="daemon-name-input">${tr('Имя демона','Daemon name')}</label><input id="daemon-name-input" class="name-input" maxlength="40" placeholder="${esc(projectKey(d))}" value="${esc(d.name || '')}"><div><button class="btn primary" type="submit">${tr('Сохранить','Save')}</button><button class="btn" type="button" data-cancel-name>${tr('Отмена','Cancel')}</button></div><span class="rename-error" role="status"></span></form>`;
  const form=container.querySelector('form'), input=form.querySelector('input'), error=form.querySelector('.rename-error');
  input.focus();input.select();let saving=false,finished=false;
  const cancel=()=>{if(!saving&&!finished){finished=true;markFormClean(form);done();}};
  form.querySelector('[data-cancel-name]').addEventListener('click',cancel);
  input.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancel();}});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving||finished)return;
    saving=true;error.textContent=tr("Сохраняем…","Saving…");form.querySelectorAll('button,input').forEach(field=>field.disabled=true);
    try{await saveName(d.id,input.value.trim());markFormClean(form);finished=true;done();}
    catch(err){error.textContent=tr("Имя не сохранено. Проверьте соединение и попробуйте ещё раз.","Name was not saved. Check the connection and try again.");}
    finally{saving=false;if(!finished){form.querySelectorAll('button,input').forEach(field=>field.disabled=false);input.focus();}}
  });
}
