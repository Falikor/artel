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
  if (button) { button.setAttribute('aria-pressed', String(value)); button.textContent = value ? tr("Автопрокрутка включена","Auto-scroll on") : tr("Автопрокрутка выключена","Auto-scroll off"); }
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
  markFormClean($('retryBlockForm'));markFormClean($('moveOffice'));
  clearInterval(drawer.timer); drawer.timer = setInterval(() => refreshDrawer(false), 1000);
  if (wasHidden) $('drawerClose').focus({preventScroll:true});
}
function closeDrawer() {
  if ($('drawer').hidden) return;
  const id = drawer.id;
  stopMonitor(); clearInterval(drawer.timer); drawer.serial++; drawer.id = null; drawer.pickChar = false;
  const panel = $('drawer');
  markFormClean(panel);
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
  if (!drawer.renaming) drawerMarkup($('drawerTitle'), `<span>${esc(displayName(d))}</span>${lastSnapshot.control !== false ? `<button class="rename" data-rename="${esc(d.id)}" aria-label="${tr('Переименовать демона','Rename daemon')}" title="${tr('Переименовать демона','Rename daemon')}">✎</button>` : ''}`);
  const stage = d.alive === false && d.stage !== 'stopped' ? 'lost' : d.stage;
  $('drawerMeta').textContent = [projectKey(d), (STAGE[stage] || STAGE.idle).label, issue, d.office_title].filter(Boolean).join(' · ');
  const tabs = [['technical',tr("Логи GigaCode","GigaCode logs")],['progress',tr("Ход работы","Activity")],['settings',tr("Настройки","Settings")],['retries',tr("Повторы","Retries")],['placement',tr("Размещение","Placement")],['agent',tr("Лог демона","Daemon log")]];
  if (issue) tabs.push(['gigacode',tr("Итог генерации","Generation result")]);
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
    drawerMarkup($('drawerActions'), `<div class="inspector-section-head"><h3>${tr('Управление','Controls')}</h3><p>${tr('Действия над текущей работой демона.','Manage the daemon’s current work.')}</p></div><div class="inspector-action-list">${editable ? controlButton(d) + (d.source === 'state' && d.alive ? `<button type="button" class="btn" data-poke="${esc(d.id)}">${tr('Проверить Jira сейчас','Check Jira now')}</button>` : '') + `<button type="button" class="btn" data-requirements>${tr('Направить на переделку','Request rework')}</button>` : `<p class="muted">${tr('Дашборд запущен в режиме просмотра.','The dashboard is read-only.')}</p>`}</div>${editable ? `<details class="inspector-social"><summary>${tr('Взаимодействие с персонажем','Character interactions')}</summary><p>${tr('Анимации в офисе не меняют задачи, настройки или память демона.','Office animations do not change tasks, settings, or the daemon’s memory.')}</p><div class="inspector-action-list"><button type="button" class="btn" data-visit>${tr('Отправить в гости','Visit colleagues')}</button><button type="button" class="btn" data-feedback="praise">${tr('Наградить','Reward')}</button><button type="button" class="btn" data-feedback="reprimand">${tr('Сделать замечание','Reprimand')}</button></div></details>` : ''}`);
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
  if (drawer.logKey !== key) { drawer.logKey = key; drawer.logText = ''; $('drawerLog').textContent = ''; $('cliStatus').textContent = tr("Загрузка журнала…","Loading log…"); }
  const url = tab === 'gigacode' && issue ? `/api/gigacode?issue=${encodeURIComponent(issue)}` : `/api/log?id=${encodeURIComponent(id)}&n=400`;
  try {
    const response = await fetch(url);
    if (!response.ok) throw Error('HTTP ' + response.status);
    const text = (await response.text()).replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/\r(?!\n)/g,'\n');
    if (serial !== drawer.serial || id !== drawer.id || tab !== drawer.tab) return;
    $('cliStatus').textContent = text ? (tab === 'gigacode' ? `${tr('Итог выполнения','Execution result')} ${issue}` : tr("Последние 400 строк · обновление каждую секунду","Last 400 lines · refreshed every second")) : tr("В этом журнале пока нет записей.","No entries in this log yet.");
    if (text !== drawer.logText) {
      drawer.logText = text;
      $('drawerLog').innerHTML = esc(text).split('\n').map(line => / - ERROR - /.test(line) ? `<span class="e">${line}</span>` : / - WARNING - /.test(line) ? `<span class="w">${line}</span>` : /✅/.test(line) ? `<span class="k">${line}</span>` : line).join('\n');
      drawerScrollEnd();
    }
  } catch (error) {
    if (serial === drawer.serial) $('cliStatus').textContent = tr("Не удалось обновить журнал. Последние записи сохранены; повторим запрос автоматически.","Could not refresh the log. Existing entries are preserved; retrying automatically.");
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
    drawerNotice(moved ? tr("Демон отправился в гости. Его постоянное место сохранено.","The daemon is visiting another office. Its permanent seat is preserved.") : tr("Сейчас визит невозможен: демон занят или нет свободных коллег.","Cannot visit now: the daemon is busy or no colleagues are available."), !moved); return;
  }
  if (button.dataset.feedback) {
    const worker = office.workers.get(drawer.id);
    if (!worker || !worker.visible || worker.lost) { drawerNotice(tr("Персонаж сейчас вне офиса. Попробуйте, когда он вернётся.","The character is outside the office. Try again when it returns."),true); return; }
    ownerReaction(drawer.id,button.dataset.feedback);
    closeDrawer(); return;
  }
  const id = drawer.id, action = button.dataset.stop ? 'stop' : button.dataset.start ? 'start' : button.dataset.poke ? 'poke' : null;
  if (!action) return;
  const daemon = lastSnapshot.daemons.find(d => d.id === id);
  if (action === 'stop' && daemon && !window.confirm(stopQuestion(daemon))) return;
  drawer.busy = true; button.disabled = true; drawerNotice(tr("Отправляем запрос…","Sending request…"));
  try {
    const result = action === 'poke' ? await pokeDemon(id) : await controlDemon(id,action);
    if (drawer.id !== id) return;
    const message = result.ok ? {stop:tr("Запрос на остановку отправлен.","Stop requested."),start:tr("Запрос на запуск отправлен.","Start requested."),poke:tr("Запрос на проверку Jira отправлен.","Jira check requested.")}[action] : CONTROL_ERRORS[result.reason] || (result.reason === 'busy' ? tr("Демон занят текущей работой.","The daemon is busy with its current work.") : tr("Действие недоступно сейчас.","This action is not available right now."));
    drawerNotice(message,!result.ok);
    if (result.ok && action !== 'poke') drawer.control = {id, until:Date.now()+12000, text:action === 'stop' ? tr("Останавливается…","Stopping…") : tr("Запускается…","Starting…")};
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
    if (placementChanged || (['retryIssue','newOfficeName'].some(id => $(id).value.trim()) && ['retries','placement'].includes(drawer.tab))) { drawerNotice(tr("В форме есть введённый текст. Сохраните его или закройте панель кнопкой ×.","This form contains edits. Save them or close the panel with ×.")); return; }
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
    if (!text) { drawerNotice(tr("Пока нет записей для копирования.","There are no entries to copy yet.")); return; }
    try { await navigator.clipboard.writeText(text); drawerNotice(tr("Журнал скопирован.","Log copied.")); }
    catch { drawerNotice(tr("Браузер не разрешил копирование. Выделите нужный текст в журнале.","The browser blocked clipboard access. Select the text you need in the log."),true); }
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
  const options=(lastSnapshot.offices||[]).map(room => `<option value="${esc(room.id)}">${esc(room.title)}</option>`).join('')+`<option value="new">＋ ${tr('Новый офис…','New office…')}</option><option value="auto">${tr('Автоматически по проекту / сервису','Automatically by project / service')}</option>`;
  const key=drawer.id+options;
  if(drawer.officeKey !== key) {
    const previous=drawer.officeKey ? $('moveOfficeSelect').value : daemon.office_id;
    $('moveOfficeSelect').innerHTML=options;
    $('moveOfficeSelect').value=[...$('moveOfficeSelect').options].some(option=>option.value===previous) ? previous : daemon.office_id;
    drawer.officeKey=key;
    $('moveOfficeStatus').textContent=daemon.office_manual ? tr("Офис выбран вручную.","Office selected manually.") : tr("Офис определяется по проекту или сервису.","Office assigned by project or service.");
  }
  $('newOfficeName').hidden=$('moveOfficeSelect').value!=='new';
  $('newOfficeName').required=$('moveOfficeSelect').value==='new';
  for(const field of $('moveOffice').querySelectorAll('input,select,button')) field.disabled=lastSnapshot.control===false||!!drawer.officeSaving;
}
$('moveOfficeSelect').onchange=() => { const isNew=$('moveOfficeSelect').value==='new'; $('newOfficeName').hidden=!isNew; $('newOfficeName').required=isNew; if(isNew)$('newOfficeName').focus(); };
$('moveOffice').onsubmit=async event => {
  event.preventDefault(); if(drawer.busy) return;
  const id=drawer.id, room=$('moveOfficeSelect').value, name=$('newOfficeName').value.trim();
  if(room==='new' && !name) { $('moveOfficeStatus').textContent=tr("Укажите название нового офиса.","Enter a name for the new office."); $('newOfficeName').focus(); return; }
  const body=room==='new'?{id,name}:{id,room}, button=event.target.querySelector('button');
  drawer.busy=true;drawer.officeSaving=true;renderOfficePicker();button.disabled=true;$('moveOfficeStatus').textContent=tr("Сохраняем размещение…","Saving placement…");
  try {
    const response=await fetch('/api/offices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json(); if(!response.ok||result.error)throw Error(result.error||tr("Не удалось сохранить размещение.","Could not save placement."));
    apply(result);
    if(drawer.id!==id)return;
    drawer.officeKey=null;$('newOfficeName').value='';renderOfficePicker();
    markFormClean($('moveOffice'));
    const updated=result.daemons.find(daemon=>daemon.id===id);if(updated)renderDrawerChrome(updated);
    $('moveOfficeStatus').textContent=tr("Размещение сохранено. Постоянное место назначено в выбранном офисе.","Placement saved. A permanent seat is assigned in the selected office.");
  } catch(error) {if(drawer.id===id)$('moveOfficeStatus').textContent=translateServerMessage(error.message);}
  finally{drawer.busy=false;drawer.officeSaving=false;button.disabled=false;if(drawer.id===id)renderOfficePicker();}
};
async function loadRetries(force=false) {
  const id=drawer.id;
  if(!id||drawer.retryLoading||drawer.retrySaving||(!force&&Date.now()-drawer.retryLoadedAt<3000))return;
  drawer.retryLoading=true;
  try {
    const response=await fetch('/api/retries?id='+encodeURIComponent(id));
    if(!response.ok)throw Error(tr("Не удалось прочитать журнал повторов. Повторим запрос автоматически.","Could not load retry history. Retrying automatically."));
    const rows=await response.json(); if(drawer.id!==id)return;
    drawer.retryLoadedAt=Date.now();const editable=lastSnapshot.control!==false;
    $('retryBlockForm').hidden=!editable;
    const key=JSON.stringify([id,rows,editable]); if(key===drawer.retryKey)return;
    // Focused decisions stay in place until the user leaves the row.
    if(!force&&document.activeElement?.closest('#retryRows'))return;
    drawer.retryKey=key;
    drawerMarkup($('retryRows'),Object.entries(rows).sort((a,b)=>(b[1].started_at||0)-(a[1].started_at||0)).map(([issue,row])=>{
      const label=row.mode==='blocked'?tr("Исключена","Excluded"):row.mode==='paused'&&row.pause_until>nowSec()?tr("Пауза до ","Paused until ")+new Date(row.pause_until*1000).toLocaleString(uiLocale()):row.needs_review?translateServerMessage(row.reason):row.status==='blocked'?tr("Ждёт уточнения в Jira","Waiting for clarification in Jira"):row.approved?tr("Повтор разрешён","Retry approved"):row.status==='running'?tr("В работе или прервана","Running or interrupted"):row.until>nowSec()?tr("Следующий повтор после ","Next retry after ")+new Date(row.until*1000).toLocaleString(uiLocale()):row.status==='done'?tr("Завершена","Completed"):tr("Автоматический повтор","Automatic retry");
      return `<article class="retry-row"><div class="retry-row-heading"><strong>${esc(issue)}</strong><span>${esc(label)}</span></div><small>${tr('Попыток','Attempts')}: ${row.attempts||0}${row.pending_transition?tr(" · только перевод Jira"," · Jira transition only"):''}</small>${editable?`<div class="inspector-action-list"><button class="btn" data-retry="resume" data-issue="${esc(issue)}">${tr('Разрешить повтор','Allow retry')}</button><button class="btn" data-retry="pause" data-issue="${esc(issue)}">${tr('Пауза на час','Pause for an hour')}</button><button class="btn" data-retry="block" data-issue="${esc(issue)}">${tr('Исключить','Exclude')}</button></div>`:''}</article>`;
    }).join('')||`<div class="inspector-empty"><h3>${tr('Повторов пока нет','No retries yet')}</h3><p>${tr('Здесь появятся предыдущие попытки. Нежелательную задачу можно заранее исключить по ключу.','Previous attempts will appear here. You can exclude an unwanted task by its key in advance.')}</p></div>`);
  }catch(error){if(drawer.id===id)$('retryStatus').textContent=translateServerMessage(error.message);}
  finally{drawer.retryLoading=false;}
}
async function retryDecision(issue,action) {
  if(drawer.retrySaving)return;const id=drawer.id;drawer.retrySaving=true;
  const buttons=[...$('retryPanel').querySelectorAll('button')];buttons.forEach(button=>button.disabled=true);$('retryStatus').textContent=tr("Сохраняем решение…","Saving decision…");
  try {
    const response=await fetch('/api/retries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,issue:issue.trim(),action})});
    const data=await response.json();if(!response.ok||!data.ok)throw Error(data.error||tr("Не удалось сохранить решение.","Could not save the decision."));
    if(drawer.id===id){$('retryStatus').textContent=tr("Сохранено. Применится перед следующей попыткой.","Saved. Applies before the next attempt.");if(action==='block'){$('retryIssue').value='';markFormClean($('retryBlockForm'));}drawer.retryKey=null;drawer.retryLoadedAt=0;}
  }catch(error){if(drawer.id===id)$('retryStatus').textContent=translateServerMessage(error.message);}
  finally{drawer.retrySaving=false;buttons.forEach(button=>button.disabled=false);if(drawer.id===id)loadRetries(true);}
}
$('retryRows').onclick=event=>{const button=event.target.closest('[data-retry]');if(button)retryDecision(button.dataset.issue,button.dataset.retry);};
$('retryBlockForm').onsubmit=event=>{event.preventDefault();retryDecision($('retryIssue').value,'block');};
function cliPurpose(value='') {
  const labels={generation:tr("Генерация","Generation"),review:tr("Ревью","Review"),rework:tr("Доработка","Rework"),explore:tr("Исследование","Exploration"),retro:tr("Ретроспектива","Retrospective")};
  return labels[value]||(value.startsWith('pr-')?tr("Замечания PR","PR feedback"):value.startsWith('memory-')?tr("Проверка памяти","Memory verification"):value);
}
