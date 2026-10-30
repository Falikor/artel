'use strict';
/* Инспектор демона. Один экран задачи за раз, без потери фокуса при обновлении. */
const drawer = { id: null, tab: 'technical', timer: null, renaming: false, serial: 0, follow: true, retryLoadedAt: 0 };
function drawerMarkup(node, html) {
  if (node && node._markup !== html) { node.innerHTML = html; node._markup = html; }
}
function drawerNotice(text, error = false) {
  const node = $('drawerNotice');
  if (node) { node.textContent = text; node.classList.toggle('is-error', error); }
}
function drawerScrollEnd() {
  const body = $('drawerBody');
  if (body && drawer.follow) body.scrollTop = body.scrollHeight;
}
function drawerFollow(value) {
  drawer.follow = value;
  const button = $('drawerFollow');
  if (button) { button.setAttribute('aria-pressed', String(value)); button.textContent = value ? 'Автопрокрутка включена' : 'Автопрокрутка выключена'; }
}
function select(id) {
  office.selected = id; renderCards();
  if (id) openDrawer(id); else closeDrawer();
}
function openDrawer(id) {
  const panel = $('drawer'), wasHidden = panel.hidden;
  if (wasHidden) drawer.returnFocus = document.activeElement;
  stopMonitor();
  drawer.id = id; drawer.serial++; drawer.fetchBusy = null; drawer.tab = 'technical'; drawer.pickChar = false;
  drawer.renaming = false; drawer.retryLoadedAt = 0; drawer.retryKey = null; drawer.officeKey = null;
  drawer.logText = ''; drawer.logKey = null; drawer.busy = false;
  drawerFollow(true); drawerNotice('');
  panel.hidden = false;
  if (typeof panel.showModal === 'function' && !panel.open) panel.showModal();
  $('featureRows').textContent = ''; $('featureRows')._markup = null;
  $('featureStatus').textContent = ''; $('retryRows').textContent = ''; $('retryRows')._markup = null;
  $('retryStatus').textContent = ''; $('drawerLog').textContent = '';
  $('retryIssue').value = ''; $('newOfficeName').value = '';
  renderOfficePicker(); renderCharPicker(); refreshDrawer(true);
  clearInterval(drawer.timer); drawer.timer = setInterval(() => refreshDrawer(false), 1000);
  if (wasHidden) $('drawerClose').focus({preventScroll:true});
}
function closeDrawer() {
  if ($('drawer').hidden) return;
  const id = drawer.id;
  stopMonitor(); clearInterval(drawer.timer); drawer.serial++; drawer.id = null; drawer.pickChar = false;
  const panel = $('drawer');
  if (typeof panel.close === 'function' && panel.open) panel.close();
  panel.hidden = true; office.selected = null; renderCards();
  const target = drawer.returnFocus?.isConnected ? drawer.returnFocus : document.querySelector(`.card[data-id="${CSS.escape(id || '')}"]`);
  if (target) target.focus({preventScroll:true});
}
function setDrawerTab(tab, focus = false) {
  if (drawer.tab === tab) return;
  drawer.tab = tab; drawer.serial++; drawer.fetchBusy = null; drawer.pickChar = tab === 'placement';
  drawerNotice(''); $('drawerBody').scrollTop = 0; refreshDrawer(true);
  if (focus) $('drawerTabs').querySelector(`[data-tab="${tab}"]`)?.focus({preventScroll:true});
}
function renderDrawerChrome(d) {
  const issue = d.issue || d.last_result?.issue;
  if (!drawer.renaming) drawerMarkup($('drawerTitle'), `<span>${esc(displayName(d))}</span>${lastSnapshot.control !== false ? `<button class="rename" data-rename="${esc(d.id)}" aria-label="Переименовать демона" title="Переименовать демона">✎</button>` : ''}`);
  const stage = d.alive === false && d.stage !== 'stopped' ? 'lost' : d.stage;
  $('drawerMeta').textContent = [projectKey(d), (STAGE[stage] || STAGE.idle).label, issue, d.office_title].filter(Boolean).join(' · ');
  const tabs = [['technical','Логи GigaCode'],['progress','Ход работы'],['settings','Настройки'],['retries','Повторы'],['placement','Размещение'],['agent','Лог демона']];
  if (issue) tabs.push(['gigacode','Итог генерации']);
  if (!tabs.some(([key]) => key === drawer.tab)) drawer.tab = 'technical';
  drawerMarkup($('drawerTabs'), tabs.map(([key,label]) => `<button id="inspector-tab-${key}" type="button" role="tab" aria-controls="drawerBody" data-tab="${key}">${label}</button>`).join(''));
  for (const tab of $('drawerTabs').querySelectorAll('[data-tab]')) {
    const on = tab.dataset.tab === drawer.tab;
    tab.classList.toggle('on', on); tab.setAttribute('aria-selected', String(on)); tab.tabIndex = on ? 0 : -1;
  }
  $('drawerBody').setAttribute('aria-labelledby', 'inspector-tab-' + drawer.tab);
  const monitoring = ['technical','progress'].includes(drawer.tab), logging = ['agent','gigacode'].includes(drawer.tab);
  $('cliMonitor').hidden = !monitoring; $('drawerLog').hidden = !logging;
  $('drawerActions').hidden = drawer.tab !== 'settings';
  $('featurePanel').hidden = drawer.tab !== 'settings'; $('featurePanel').open = drawer.tab === 'settings';
  $('retryPanel').hidden = drawer.tab !== 'retries'; $('retryPanel').open = drawer.tab === 'retries';
  $('moveOffice').hidden = drawer.tab !== 'placement';
  $('drawerChars').hidden = drawer.tab !== 'placement';
  $('cliStatus').hidden = !logging;
  $('drawerToolbar').hidden = false;
  $('drawerFollow').hidden = !monitoring && !logging; $('drawerCopy').hidden = !monitoring && !logging;
  $('drawerBody').setAttribute('role','tabpanel');
  drawer.pickChar = drawer.tab === 'placement';
  if (drawer.tab === 'settings') {
    const editable = lastSnapshot.control !== false;
    drawerMarkup($('drawerActions'), `<div class="inspector-section-head"><h3>Управление</h3><p>Действия над текущей работой демона.</p></div><div class="inspector-action-list">${editable ? controlButton(d) + (d.source === 'state' && d.alive ? '<button type="button" class="btn" data-poke="'+esc(d.id)+'">Проверить Jira сейчас</button>' : '') + '<button type="button" class="btn" data-requirements>Направить на переделку</button>' : '<p class="muted">Дашборд запущен в режиме просмотра.</p>'}</div>${editable ? '<details class="inspector-social"><summary>Взаимодействие с персонажем</summary><p>Анимации в офисе не меняют задачи, настройки или память демона.</p><div class="inspector-action-list"><button type="button" class="btn" data-visit>Отправить в гости</button><button type="button" class="btn" data-feedback="praise">Наградить</button><button type="button" class="btn" data-feedback="reprimand">Сделать замечание</button></div></details>' : ''}`);
  }
  if (drawer.tab === 'placement') { renderOfficePicker(); renderCharPicker(); }
  return { issue, monitoring, logging };
}
async function refreshDrawer(scroll = false) {
  const d = lastSnapshot.daemons.find(x => x.id === drawer.id);
  if (!d || $('drawer').hidden) return;
  const {issue, monitoring, logging} = renderDrawerChrome(d);
  if (drawer.tab === 'settings') loadFeaturePanel(scroll);
  if (drawer.tab === 'retries') loadRetries(scroll);
  if (monitoring) { startMonitor(d.id, drawer.tab === 'technical'); return; }
  stopMonitor();
  if (!logging || (drawer.fetchBusy && !scroll)) return;
  const serial = ++drawer.serial, id = drawer.id, tab = drawer.tab;
  drawer.fetchBusy = serial;
  const key = [id,tab,issue].join(':');
  if (drawer.logKey !== key) { drawer.logKey = key; drawer.logText = ''; $('drawerLog').textContent = ''; $('cliStatus').textContent = 'Загрузка журнала…'; }
  const url = tab === 'gigacode' && issue ? `/api/gigacode?issue=${encodeURIComponent(issue)}` : `/api/log?id=${encodeURIComponent(id)}&n=400`;
  try {
    const response = await fetch(url);
    if (!response.ok) throw Error('HTTP ' + response.status);
    const text = (await response.text()).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/\r(?!\n)/g,'\n');
    if (serial !== drawer.serial || id !== drawer.id || tab !== drawer.tab) return;
    $('cliStatus').textContent = text ? (tab === 'gigacode' ? `Итог выполнения ${issue}` : 'Последние 400 строк · обновление каждую секунду') : 'В этом журнале пока нет записей.';
    if (text !== drawer.logText) {
      drawer.logText = text;
      $('drawerLog').innerHTML = esc(text).split('\n').map(line => / - ERROR - /.test(line) ? `<span class="e">${line}</span>` : / - WARNING - /.test(line) ? `<span class="w">${line}</span>` : /✅/.test(line) ? `<span class="k">${line}</span>` : line).join('\n');
      drawerScrollEnd();
    }
  } catch (error) {
    if (serial === drawer.serial) $('cliStatus').textContent = 'Не удалось обновить журнал. Последние записи сохранены; повторим запрос автоматически.';
  } finally { if (drawer.fetchBusy === serial) drawer.fetchBusy = null; }
}
async function handleDrawerAction(event) {
  const button = event.target.closest('button');
  if (!button || drawer.busy) return;
  if (button.hasAttribute('data-requirements')) {
    workspace.requirementsDaemon = drawer.id; closeDrawer(); setView('requirements'); return;
  }
  if (button.hasAttribute('data-visit')) {
    const daemon = lastSnapshot.daemons.find(d => d.id === drawer.id);
    const moved = daemon && (lastSnapshot.offices || []).filter(room => room.id !== daemon.office_id).some(room => startOfficeVisit(daemon.id,room.id,true));
    drawerNotice(moved ? 'Демон отправился в гости. Его постоянное место сохранено.' : 'Сейчас визит невозможен: демон занят или нет свободных коллег.', !moved); return;
  }
  if (button.dataset.feedback) {
    const worker = office.workers.get(drawer.id);
    if (!worker || !worker.visible || worker.lost) { drawerNotice('Персонаж сейчас вне офиса. Попробуйте, когда он вернётся.',true); return; }
    ownerReaction(drawer.id,button.dataset.feedback);
    closeDrawer(); return;
  }
  const id = drawer.id, action = button.dataset.stop ? 'stop' : button.dataset.start ? 'start' : button.dataset.poke ? 'poke' : null;
  if (!action) return;
  const daemon = lastSnapshot.daemons.find(d => d.id === id);
  if (action === 'stop' && daemon && !window.confirm(stopQuestion(daemon))) return;
  drawer.busy = true; button.disabled = true; drawerNotice('Отправляем запрос…');
  try {
    const result = action === 'poke' ? await pokeDemon(id) : await controlDemon(id,action);
    if (drawer.id !== id) return;
    const message = result.ok ? {stop:'Запрос на остановку отправлен.',start:'Запрос на запуск отправлен.',poke:'Запрос на проверку Jira отправлен.'}[action] : CONTROL_ERRORS[result.reason] || (result.reason === 'busy' ? 'Демон занят текущей работой.' : 'Действие недоступно сейчас.');
    drawerNotice(message,!result.ok);
    if (result.ok && action !== 'poke') drawer.control = {id, until:Date.now()+12000, text:action === 'stop' ? 'Останавливается…' : 'Запускается…'};
  } finally { drawer.busy = false; if (button.isConnected) button.disabled = false; if (drawer.id === id) refreshDrawer(false); }
}
function setupInput() {
  $('cards').addEventListener('click', event => { const card=event.target.closest('.card'); if(card) select(office.selected === card.dataset.id ? null : card.dataset.id); });
  $('cards').addEventListener('keydown', event => {
    if (!['Enter',' '].includes(event.key) || event.target !== event.target.closest('.card')) return;
    event.preventDefault(); select(event.target.dataset.id);
  });
  $('drawerClose').addEventListener('click', closeDrawer);
  for(const id of ['featurePanel','retryPanel']) {
    const summary=$(id).querySelector('summary');summary.tabIndex=-1;summary.addEventListener('click',event=>event.preventDefault());
  }
  $('drawerBackdrop')?.addEventListener('click', closeDrawer);
  $('drawer').addEventListener('cancel', event => {
    event.preventDefault();
    if (drawer.renaming || drawer.busy || drawer.retrySaving || drawer.characterSaving || featureSaving || document.activeElement?.tagName === 'SELECT') return;
    const daemon = lastSnapshot.daemons.find(item => item.id === drawer.id);
    const placementChanged = drawer.tab === 'placement' && $('moveOfficeSelect').value !== daemon?.office_id;
    if (placementChanged || (['retryIssue','newOfficeName'].some(id => $(id).value.trim()) && ['retries','placement'].includes(drawer.tab))) { drawerNotice('В форме есть введённый текст. Сохраните его или закройте панель кнопкой ×.'); return; }
    closeDrawer();
  });
  $('drawerChars').addEventListener('click', event => {
    const variant = event.target.closest('[data-variant]'), character = event.target.closest('[data-char]');
    if (!drawer.id || lastSnapshot.control === false) return;
    if (variant) chooseAppearance(drawer.id, Number(variant.dataset.variant));
    else if (character) chooseCharacter(drawer.id,character.dataset.char);
  });
  $('drawerTitle').addEventListener('click', event => {
    const button = event.target.closest('[data-rename]'); if(!button) return;
    const daemon = lastSnapshot.daemons.find(d => d.id === button.dataset.rename); if(!daemon) return;
    drawer.renaming = true;
    startRename($('drawerTitle'),daemon,() => { drawer.renaming = false; $('drawerTitle')._markup = null; refreshDrawer(false); $('drawerTitle').querySelector('[data-rename]')?.focus({preventScroll:true}); });
  });
  $('drawerTabs').addEventListener('click', event => { const tab=event.target.closest('[data-tab]'); if(tab) setDrawerTab(tab.dataset.tab); });
  $('drawerTabs').addEventListener('keydown', event => {
    if (!['ArrowRight','ArrowLeft','Home','End'].includes(event.key)) return;
    const tabs = [...$('drawerTabs').querySelectorAll('[data-tab]')], current=tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    setDrawerTab(tabs[next].dataset.tab,true); tabs[next].scrollIntoView({block:'nearest',inline:'nearest'});
  });
  $('drawerActions').addEventListener('click',handleDrawerAction);
  $('drawerFollow').addEventListener('click',() => { drawerFollow(!drawer.follow); drawerScrollEnd(); });
  $('drawerBody').addEventListener('scroll', () => {
    if (!['technical','progress','agent','gigacode'].includes(drawer.tab)) return;
    const body=$('drawerBody');
    if(drawer.follow && body.scrollHeight > body.clientHeight+40 && body.scrollHeight-body.scrollTop-body.clientHeight >= 40) drawerFollow(false);
  },{passive:true});
  $('drawerCopy').addEventListener('click',async () => {
    const text = ['technical','progress'].includes(drawer.tab) ? monitorText() : drawer.logText;
    if (!text) { drawerNotice('Пока нет записей для копирования.'); return; }
    try { await navigator.clipboard.writeText(text); drawerNotice('Журнал скопирован.'); }
    catch { drawerNotice('Браузер не разрешил копирование. Выделите нужный текст в журнале.',true); }
  });
  const canvas=$('scene');
  const point=event => { const rect=canvas.getBoundingClientRect(); return [(event.clientX-rect.left-office.ox)/office.scale,(event.clientY-rect.top-office.oy)/office.scale]; };
  const worker=event => { const [x,y]=point(event); return [...office.workers.values()].sort((a,b)=>b.pos[1]-a.pos[1]).find(w=>w.hit(x,y)); };
  canvas.addEventListener('mousemove',event => { const [x,y]=point(event); canvas.classList.toggle('pointer',!!worker(event)||!!(office.cat&&office.cat.hit(x,y))); });
  canvas.addEventListener('dblclick',event => { const w=worker(event); if(w) {event.preventDefault();pokeDemon(w.id);} });
  canvas.addEventListener('click',event => { const [x,y]=point(event); if(office.cat&&office.cat.hit(x,y)) {office.cat.say(pick(CAT_LINES.cat),office.t);return;} const w=worker(event); select(w ? w.id : null); });
}
function renderOfficePicker() {
  const daemon = lastSnapshot.daemons.find(d => d.id === drawer.id); if(!daemon) return;
  const options=(lastSnapshot.offices||[]).map(room => `<option value="${esc(room.id)}">${esc(room.title)}</option>`).join('')+'<option value="new">＋ Новый офис…</option><option value="auto">Автоматически по проекту / сервису</option>';
  const key=drawer.id+options;
  if(drawer.officeKey !== key) {
    const previous=drawer.officeKey ? $('moveOfficeSelect').value : daemon.office_id;
    $('moveOfficeSelect').innerHTML=options;
    $('moveOfficeSelect').value=[...$('moveOfficeSelect').options].some(option=>option.value===previous) ? previous : daemon.office_id;
    drawer.officeKey=key;
    $('moveOfficeStatus').textContent=daemon.office_manual ? 'Офис выбран вручную.' : 'Офис определяется по проекту или сервису.';
  }
  $('newOfficeName').hidden=$('moveOfficeSelect').value!=='new';
  $('newOfficeName').required=$('moveOfficeSelect').value==='new';
  for(const field of $('moveOffice').querySelectorAll('input,select,button')) field.disabled=lastSnapshot.control===false||!!drawer.officeSaving;
}
$('moveOfficeSelect').onchange=() => { const isNew=$('moveOfficeSelect').value==='new'; $('newOfficeName').hidden=!isNew; $('newOfficeName').required=isNew; if(isNew)$('newOfficeName').focus(); };
$('moveOffice').onsubmit=async event => {
  event.preventDefault(); if(drawer.busy) return;
  const id=drawer.id, room=$('moveOfficeSelect').value, name=$('newOfficeName').value.trim();
  if(room==='new' && !name) { $('moveOfficeStatus').textContent='Укажите название нового офиса.'; $('newOfficeName').focus(); return; }
  const body=room==='new'?{id,name}:{id,room}, button=event.target.querySelector('button');
  drawer.busy=true;drawer.officeSaving=true;renderOfficePicker();button.disabled=true;$('moveOfficeStatus').textContent='Сохраняем размещение…';
  try {
    const response=await fetch('/api/offices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json(); if(!response.ok||result.error)throw Error(result.error||'Не удалось сохранить размещение.');
    apply(result);
    if(drawer.id!==id)return;
    drawer.officeKey=null;$('newOfficeName').value='';renderOfficePicker();
    const updated=result.daemons.find(daemon=>daemon.id===id);if(updated)renderDrawerChrome(updated);
    $('moveOfficeStatus').textContent='Размещение сохранено. Постоянное место назначено в выбранном офисе.';
  } catch(error) {if(drawer.id===id)$('moveOfficeStatus').textContent=error.message;}
  finally{drawer.busy=false;drawer.officeSaving=false;button.disabled=false;if(drawer.id===id)renderOfficePicker();}
};
async function loadRetries(force=false) {
  const id=drawer.id;
  if(!id||drawer.retryLoading||drawer.retrySaving||(!force&&Date.now()-drawer.retryLoadedAt<3000))return;
  drawer.retryLoading=true;
  try {
    const response=await fetch('/api/retries?id='+encodeURIComponent(id));
    if(!response.ok)throw Error('Не удалось прочитать журнал повторов. Повторим запрос автоматически.');
    const rows=await response.json(); if(drawer.id!==id)return;
    drawer.retryLoadedAt=Date.now();const editable=lastSnapshot.control!==false;
    $('retryBlockForm').hidden=!editable;
    const key=JSON.stringify([id,rows,editable]); if(key===drawer.retryKey)return;
    // Focused decisions stay in place until the user leaves the row.
    if(!force&&document.activeElement?.closest('#retryRows'))return;
    drawer.retryKey=key;
    drawerMarkup($('retryRows'),Object.entries(rows).sort((a,b)=>(b[1].started_at||0)-(a[1].started_at||0)).map(([issue,row])=>{
      const label=row.mode==='blocked'?'Исключена':row.mode==='paused'&&row.pause_until>nowSec()?'Пауза до '+new Date(row.pause_until*1000).toLocaleString('ru-RU'):row.needs_review?row.reason:row.status==='blocked'?'Ждёт уточнения в Jira':row.approved?'Повтор разрешён':row.status==='running'?'В работе или прервана':row.until>nowSec()?'Следующий повтор после '+new Date(row.until*1000).toLocaleString('ru-RU'):row.status==='done'?'Завершена':'Автоматический повтор';
      return `<article class="retry-row"><div class="retry-row-heading"><strong>${esc(issue)}</strong><span>${esc(label)}</span></div><small>Попыток: ${row.attempts||0}${row.pending_transition?' · только перевод Jira':''}</small>${editable?`<div class="inspector-action-list"><button class="btn" data-retry="resume" data-issue="${esc(issue)}">Разрешить повтор</button><button class="btn" data-retry="pause" data-issue="${esc(issue)}">Пауза на час</button><button class="btn" data-retry="block" data-issue="${esc(issue)}">Исключить</button></div>`:''}</article>`;
    }).join('')||'<div class="inspector-empty"><h3>Повторов пока нет</h3><p>Здесь появятся предыдущие попытки. Нежелательную задачу можно заранее исключить по ключу.</p></div>');
  }catch(error){if(drawer.id===id)$('retryStatus').textContent=error.message;}
  finally{drawer.retryLoading=false;}
}
async function retryDecision(issue,action) {
  if(drawer.retrySaving)return;const id=drawer.id;drawer.retrySaving=true;
  const buttons=[...$('retryPanel').querySelectorAll('button')];buttons.forEach(button=>button.disabled=true);$('retryStatus').textContent='Сохраняем решение…';
  try {
    const response=await fetch('/api/retries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,issue:issue.trim(),action})});
    const data=await response.json();if(!response.ok||!data.ok)throw Error(data.error||'Не удалось сохранить решение.');
    if(drawer.id===id){$('retryStatus').textContent='Сохранено. Применится перед следующей попыткой.';if(action==='block')$('retryIssue').value='';drawer.retryKey=null;drawer.retryLoadedAt=0;}
  }catch(error){if(drawer.id===id)$('retryStatus').textContent=error.message;}
  finally{drawer.retrySaving=false;buttons.forEach(button=>button.disabled=false);if(drawer.id===id)loadRetries(true);}
}
$('retryRows').onclick=event=>{const button=event.target.closest('[data-retry]');if(button)retryDecision(button.dataset.issue,button.dataset.retry);};
$('retryBlockForm').onsubmit=event=>{event.preventDefault();retryDecision($('retryIssue').value,'block');};
function cliPurpose(value='') {
  const labels={generation:'Генерация',review:'Ревью',rework:'Доработка',explore:'Исследование',retro:'Ретроспектива'};
  return labels[value]||(value.startsWith('pr-')?'Замечания PR':value.startsWith('memory-')?'Проверка памяти':value);
}
