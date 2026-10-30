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
  if (d.alive) return `<button data-stop="${esc(d.id)}" class="ctl stop" title="Прервать текущую работу и остановить демона">Остановить</button>`;
  return `<button data-start="${esc(d.id)}" class="ctl start" title="Запуск через супервизор (artel.py)">Запустить</button>`;
}

function stopQuestion(d) {
  const name = displayName(d);
  const busy = { generating: 'пишет код', rework: 'дорабатывает код', reviewing: 'проводит ревью', exploring: 'изучает задачу',
    git: 'пушит ветку', jenkins: 'запускает деплой', jira: 'переводит задачу' }[d.stage];
  return busy
    ? `Остановить «${name}»?\n\nСейчас он ${busy}${d.issue ? ' ' + d.issue : ''}. Работа будет прервана, а задача при следующем запуске начнётся заново.`
    : `Остановить «${name}»?`;
}

async function controlDemon(id, action) {
  let res = { ok: false, reason: 'network' };
  try { res = await (await fetch(`/api/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }) })).json(); } catch { /* сервер недоступен */ }
  const w = office.workers.get(id), t = office.t;
  if (res.ok && w && action === 'stop') w.sayLine(pick(['Ухожу…', 'Понял, заканчиваю', 'Сохраняюсь и ухожу']), t, 2.6);
  return res;
}

const CONTROL_ERRORS = {
  no_supervisor: 'Запуск с дашборда — только под супервизором: python3 artel.py start',
  no_config: 'Неизвестен конфиг демона', running: 'Уже работает', offline: 'Демон уже не работает',
  old: 'Демон на другом компьютере и не умеет останавливаться по запросу — обновите его',
  readonly: 'Дашборд запущен только для просмотра (--no-control)', network: 'Нет связи с сервером',
};

// ------------------------------------------------------------------ имена
async function saveName(id, name) {
  const res = await fetch('/api/names', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, name }) });
  if (!res.ok) throw new Error('не удалось сохранить имя');
  const names = await res.json();
  for (const d of lastSnapshot.daemons) d.name = names[d.id] || null;  // SSE подтвердит через секунду
  renderCards();
  return names;
}

// Переименование с явным сохранением; ошибки остаются рядом с введённым именем.
function startRename(container, d, done) {
  container.innerHTML = `<form class="rename-form"><label class="sr-only" for="daemon-name-input">Имя демона</label><input id="daemon-name-input" class="name-input" maxlength="40" placeholder="${esc(projectKey(d))}" value="${esc(d.name || '')}"><div><button class="btn primary" type="submit">Сохранить</button><button class="btn" type="button" data-cancel-name>Отмена</button></div><span class="rename-error" role="status"></span></form>`;
  const form=container.querySelector('form'), input=form.querySelector('input'), error=form.querySelector('.rename-error');
  input.focus();input.select();let saving=false,finished=false;
  const cancel=()=>{if(!saving&&!finished){finished=true;done();}};
  form.querySelector('[data-cancel-name]').addEventListener('click',cancel);
  input.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancel();}});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving||finished)return;
    saving=true;error.textContent='Сохраняем…';form.querySelectorAll('button,input').forEach(field=>field.disabled=true);
    try{await saveName(d.id,input.value.trim());finished=true;done();}
    catch(err){error.textContent='Имя не сохранено. Проверьте соединение и попробуйте ещё раз.';}
    finally{saving=false;if(!finished){form.querySelectorAll('button,input').forEach(field=>field.disabled=false);input.focus();}}
  });
}
