'use strict';
/* The building is a live overview; only the selected office creates animated workers. */
const buildingView = { room: storage.get('artel-room', null), rendered: null, dragging: null, editing: null, busy: false };
const LOOKS = [tr("Исходный", "Original"), tr("Бирюза", "Teal"), tr("Роза", "Rose"), tr("Янтарь", "Amber"), tr("Индиго", "Indigo"), tr("Шалфей", "Sage")];
const LOOK_COLORS = ['#b9b4cd', '#42b9af', '#d86b99', '#dfa950', '#8689e2', '#8dab68'];
function visibleDaemons() {
  return buildingView.room ? lastSnapshot.daemons.filter(d => socialRoom(d) === buildingView.room).map((d,i) => socialRoom(d) !== d.office_id ? {...d, office_slot:SEATS.length+i, guest:true} : d) : [];
}
function needsAttention(d) {
  return d.stage === 'error' || (d.alive === false && d.stage !== 'stopped') ||
    (d.last_error && nowSec() - d.last_error.t < 900);
}
function roomStats(ds) {
  return { bad: ds.filter(needsAttention).length,
    busy: ds.filter(d => d.alive !== false && ['generating','reviewing','rework','git','jenkins','jira'].includes(d.stage)).length };
}
// Search is shared by the building and the current office roster. It never changes seats.
const rosterFilter = {query:'', status:'all'};
function matchesDemon(d, room) {
  const stage = d.alive === false && d.stage !== 'stopped' ? 'lost' : d.stage;
  const status = rosterFilter.status;
  if (status === 'attention' && !needsAttention(d)) return false;
  if (status === 'busy' && !roomStats([d]).busy) return false;
  if (status === 'idle' && (d.alive === false || !['idle','polling','starting'].includes(stage))) return false;
  if (status === 'offline' && !['lost','stopped'].includes(stage)) return false;
  const haystack = [displayName(d), d.id, d.issue, d.last_task?.issue, d.detail?.service, room?.title, room?.project, room?.building_title].filter(Boolean).join(' ').toLocaleLowerCase();
  return !rosterFilter.query || haystack.includes(rosterFilter.query);
}
function filteredDaemons(ds) {
  return ds.filter(d => matchesDemon(d, (lastSnapshot.offices || []).find(r => r.id === d.office_id)));
}
// Live snapshots must not steal keyboard focus or reset scrolling.
function replaceRosterContent(box, html) {
  if (box.innerHTML === html) return;
  const active = box.contains(document.activeElement) ? document.activeElement : null;
  const data = active ? Object.entries(active.dataset).find(([k]) => ['id','room','resident','renameRoom','deleteRoom','moveRoom'].includes(k)) : null;
  const scroll = box.scrollTop;
  box.innerHTML = html;
  box.scrollTop = scroll;
  if (data) {
    const replacement = [...box.querySelectorAll('button,[tabindex]')].find(el => el.dataset[data[0]] === data[1]);
    (replacement || box.querySelector('button,[tabindex]') || $('buildingSearch'))?.focus({preventScroll:true});
  }
}
function renderBuilding() {
  if (buildingView.dragging || buildingView.editing) return;
  const rooms = [...(lastSnapshot.offices || [])].sort((a,b) => (b.building_level || 0) - (a.building_level || 0) || a.id.localeCompare(b.id));
  if (buildingView.room && !rooms.some(r => r.id === buildingView.room)) buildingView.room = null;
  const all = roomStats(lastSnapshot.daemons);
  const filtering = !!rosterFilter.query || rosterFilter.status !== 'all';
  const base = buildingView.room ? visibleDaemons() : lastSnapshot.daemons;
  const matched = filteredDaemons(base);
  if ($('buildingResultCount')) $('buildingResultCount').textContent = filtering ? tr(`Найдено ${matched.length} из ${base.length}`, `Showing ${matched.length} of ${base.length}`) : tr(`${base.length} демонов`, `${base.length} daemons`);
  $('buildingTotals').textContent = tr(`${rooms.length} офисов · ${lastSnapshot.daemons.length} демонов · ${all.busy} работают`, `${rooms.length} offices · ${lastSnapshot.daemons.length} daemons · ${all.busy} working`);
  const html = rooms.map(r => {
    const ds = lastSnapshot.daemons.filter(d => d.office_id === r.id), counts = roomStats(ds);
    const shown = ds.filter(d => matchesDemon(d, r)).sort((a,b) => (a.office_slot ?? 0) - (b.office_slot ?? 0));
    const matchesEmpty = !ds.length && rosterFilter.status === 'all' && (!rosterFilter.query || `${r.title} ${r.project} ${cityRoomBuildingTitle(r)}`.toLocaleLowerCase().includes(rosterFilter.query));
    if (filtering && !shown.length && !matchesEmpty) return '';
    const guests = lastSnapshot.daemons.filter(d => d.office_id !== r.id && socialRoom(d) === r.id).length;
    return `<article data-drop-room="${esc(r.id)}" class="room ${counts.bad ? 'room-alert' : ''}">
      <button type="button" class="room-open" data-room="${esc(r.id)}" aria-label="${tr('Открыть офис', 'Open office')} ${esc(r.title)}, ${esc(cityAddressLabel(r,rooms.length-rooms.indexOf(r)))}"><span class="floor-level">${r.building_level || rooms.length - rooms.indexOf(r)}<small>${tr('этаж', 'floor')}</small></span><span class="room-label">${esc(cityAddressLabel(r,rooms.length-rooms.indexOf(r)))} · ${esc(r.project || tr("Офис", "Office"))}</span><h3>${esc(r.title)}</h3>
      <span class="room-counts">${tr(`${ds.length} из ${r.capacity} мест · ${counts.busy} работают`, `${ds.length} of ${r.capacity} seats · ${counts.busy} working`)}${guests ? tr(` · ${guests} в гостях`, ` · ${guests} visiting`) : ''}</span><b aria-hidden="true">${tr('Открыть офис', 'Open office')} →</b></button>
      ${counts.bad ? `<p class="room-attention"><span aria-hidden="true">!</span> ${tr('Требуют внимания:', 'Needs attention:')} ${counts.bad}</p>` : ''}
      <div class="room-seats">${shown.map(d => {
        const stage = d.alive === false && d.stage !== 'stopped' ? 'lost' : d.stage;
        return `<button type="button" draggable="false" class="resident ${needsAttention(d) ? 'resident-alert' : ''}" data-resident="${esc(d.id)}" aria-label="${esc(displayName(d))}: ${esc((STAGE[stage] || STAGE.idle).label)}. ${tr('Место', 'Seat')} ${Number.isInteger(d.office_slot) ? d.office_slot+1 : '—'}" title="${esc(displayName(d))} · ${esc((STAGE[stage] || STAGE.idle).label)}. ${tr('Перетащите мышью для переселения.', 'Drag to move to another office.')}">
          <img draggable="false" src="${appearanceThumb(d)}" alt=""><span class="resident-info"><span>${esc(displayName(d))}</span><small>${social.visits.has(d.id) ? tr("В гостях · ", "Visiting · ") : ''}${esc((STAGE[stage] || STAGE.idle).label)}</small></span><span class="resident-seat">${Number.isInteger(d.office_slot) ? d.office_slot+1 : '—'}</span></button>`;
      }).join('') || `<p class="room-empty">${tr('Офис свободен', 'Office available')}<span>${tr('Переселите сюда демона из другого офиса.', 'Move a daemon here from another office.')}</span></p>`}</div>
      <div class="room-actions"><button type="button" class="btn" data-rename-room="${esc(r.id)}">${tr('Переименовать', 'Rename')}</button>
        <button type="button" class="btn" data-move-room="${esc(r.id)}" ${!ds.length || rooms.length < 2 ? 'disabled' : ''}>${tr('Переселить…', 'Move…')}</button>
        <button type="button" class="btn room-delete" data-delete-room="${esc(r.id)}" ${(r.occupied || ds.length) ? `disabled title="${tr('Переселите всех закреплённых демонов, включая отсутствующих', 'Move all assigned daemons first, including offline daemons')}"` : ''}>${tr('Удалить', 'Delete')}</button>
        ${r.occupied > ds.length ? `<small>${tr(`Ещё ${r.occupied-ds.length} мест закреплено за отсутствующими демонами`, `${r.occupied-ds.length} more seats reserved for offline daemons`)}</small>` : ''}</div></article>`;
  }).join('') || `<div class="empty">${filtering ? tr("Ничего не найдено. Измените запрос или статус.", "No matches. Change the search or status filter.") : tr("Пока нет офисов. Они появятся автоматически при подключении демонов.", "No offices yet. They appear automatically when daemons connect.")}</div>`;
  replaceRosterContent($('buildingRooms'), html);
  if (typeof renderCityRooms === 'function') renderCityRooms(rooms);
  const options = rooms.map(r => `<option value="${esc(r.id)}">${esc(cityAddressLabel(r))} · ${esc(r.title)}</option>`).join('');
  if ($('officeSelect').innerHTML !== options) $('officeSelect').innerHTML = options;
  $('officeSelect').value = buildingView.room || '';
  const room = rooms.find(r => r.id === buildingView.room);
  $('officeTitle').textContent = room ? room.title : '';
  const elsewhere = lastSnapshot.daemons.filter(d => d.office_id !== buildingView.room && needsAttention(d));
  $('otherOffices').textContent = elsewhere.length ? tr(`В других офисах требуют внимания: ${elsewhere.length}`, `Needs attention in other offices: ${elsewhere.length}`) : '';
  $('building').hidden = !!room;
  $('officeNav').hidden = !room;
  $('officeLayout').hidden = !room;
  if (!room) $('summary').textContent = tr(`${all.busy} работают · ${all.bad} требуют внимания`, `${all.busy} working · ${all.bad} need attention`);
}
function refreshRosterFilter() {
  rosterFilter.query = ($('buildingSearch')?.value || '').trim().toLocaleLowerCase();
  rosterFilter.status = $('buildingFilter')?.value || 'all';
  renderBuilding(); renderCards();
}
$('buildingSearch')?.addEventListener('input', refreshRosterFilter);
$('buildingFilter')?.addEventListener('change', refreshRosterFilter);
function openOffice(id) {
  buildingView.room = id;
  storage.set('artel-room', id);
  closeDrawer();
  renderBuilding(); syncOffice(); resize(); renderCards();
}
function syncOffice() {
  if (buildingView.rendered !== buildingView.room) {
    for (const w of office.workers.values()) w.destroy();
    office.workers.clear(); office.reserved.clear(); office.spots.clear(); timers.length = 0;
    office.game = null; cabinet.seq = null; cabinet.state = 0; cabinet.console = 'drawer';
    office.nextPlan = office.t + 1;
    for (const door of office.doors) { door.p = 0; door.holdUntil = 0; }
    buildingView.rendered = buildingView.room;
  }
  const ds = visibleDaemons(), ids = new Set(ds.map(d => d.id));
  for (const d of ds) {
    let w = office.workers.get(d.id);
    // The roster arrives independently of images. Never construct a worker without a drawable sprite.
    const character = office.plate && charFor(d, d.office_slot);
    if (!character) { if (w) { w.destroy(); office.workers.delete(d.id); } continue; }
    if (w && w.slot !== d.office_slot) { w.destroy(); office.workers.delete(d.id); w = null; }
    if (!w) { w = new Worker(d, d.office_slot); office.workers.set(d.id, w); w.ingest(d, true); if (d.guest) { w.endPlan(office.t,true); w.mode='stand'; w.visible=true; w.pos=[...N.door_out]; w.node='door_out'; w.place=null; w.goTo(w.seatPlace(),office.t); w.sayLine(tr("Привет! Зашёл в гости", "Hi! Just visiting"),office.t,4); } }
    else { w.char = character; w.ingest(d, false); }
  }
  for (const [id,w] of office.workers) if (!ids.has(id)) { w.destroy(); office.workers.delete(id); }
}
$('backBuilding').onclick = () => openOffice(null);
$('officeSelect').onchange = e => openOffice(e.target.value);
$('buildingRooms').onclick = e => {
  if (buildingView.busy || buildingView.dragging || Date.now() < (buildingView.suppressClickUntil || 0)) return;
  const rename = e.target.closest('[data-rename-room]');
  if (rename) { editRoomName(rename); return; }
  const move = e.target.closest('[data-move-room]');
  if (move) { editRoomMove(move); return; }
  const remove = e.target.closest('[data-delete-room]');
  if (remove) { roomAction({action:'delete',room:remove.dataset.deleteRoom}, tr("Пустой офис удалён", "Empty office deleted")); return; }

  const resident = e.target.closest('[data-resident]');
  if (resident) {
    const d = lastSnapshot.daemons.find(x => x.id === resident.dataset.resident);
    if (d) { openOffice(socialRoom(d)); select(d.id); }
    return;
  }
  const room = e.target.closest('[data-room]');
  if (room) openOffice(room.dataset.room);
};

async function roomAction(body, message) {
  if (buildingView.busy) return false;
  buildingView.busy = true;
  $('buildingRooms').setAttribute('aria-busy','true');
  $('buildingStatus').textContent = tr("Сохраняем…", "Saving…");
  try {
    const response = await fetch('/api/offices', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const snap = await response.json();
    if (!response.ok || snap.error) throw new Error(translateServerMessage(snap.error) || tr("Не удалось сохранить. Попробуйте ещё раз.", "Could not save. Try again."));
    apply(snap);
    $('buildingStatus').textContent = message;
    return true;
  } catch (error) { $('buildingStatus').textContent = translateServerMessage(error.message); return false; }
  finally { buildingView.busy = false; $('buildingRooms').removeAttribute('aria-busy'); }
}
function roomInlineForm(button, html, action) {
  const room = button.closest('[data-drop-room]'), id = room.dataset.dropRoom;
  const focusKey = Object.entries(button.dataset)[0];
  buildingView.editing = id;
  const form = document.createElement('form'); form.className = 'room-name-form';
  form.innerHTML = html + `<div class="room-form-actions"><button type="submit" class="btn primary">${tr('Сохранить', 'Save')}</button><button type="button" class="btn">${tr('Отмена', 'Cancel')}</button></div><p class="room-form-status" role="status"></p>`;
  button.parentElement.replaceWith(form);
  const cancel = () => {
    if (buildingView.busy) return;
    buildingView.editing = null; renderBuilding();
    [...$('buildingRooms').querySelectorAll('button')].find(el => el.dataset[focusKey[0]] === focusKey[1])?.focus({preventScroll:true});
  };
  form.querySelector('[type="button"]').onclick = cancel;
  form.onkeydown = e => { if (e.key === 'Escape') { e.preventDefault(); cancel(); } };
  form.onsubmit = async e => {
    e.preventDefault();
    const controls = [...form.querySelectorAll('button,input,select')];
    const request = action(new FormData(form));
    controls.forEach(el => el.disabled = true);
    const ok = await roomAction(request.body, request.message);
    controls.forEach(el => el.disabled = false);
    if (ok) { markFormClean(form); cancel(); }
    else form.querySelector('.room-form-status').textContent = $('buildingStatus').textContent;
  };
  form.querySelector('input,select')?.focus();
  form.querySelector('input')?.select();
}
function editRoomName(button) {
  const id = button.dataset.renameRoom, room = lastSnapshot.offices.find(r => r.id === id);
  if (!room) return;
  roomInlineForm(button, `<label>${tr('Название офиса', 'Office name')}<input name="name" aria-label="${tr('Новое название офиса', 'New office name')}" maxlength="60" required value="${esc(room.title)}"></label>`, data => ({body:{action:'rename',room:id,name:data.get('name').trim()},message:tr("Название офиса сохранено", "Office name saved")}));
}
function editRoomMove(button) {
  const id = button.dataset.moveRoom;
  const ds = lastSnapshot.daemons.filter(d => d.office_id === id);
  const targets = (lastSnapshot.offices || []).filter(r => r.id !== id);
  if (!ds.length || !targets.length) return;
  roomInlineForm(button, `<label>${tr('Демон', 'Daemon')}<select name="id" aria-label="${tr('Демон для переселения', 'Daemon to move')}">${ds.map(d => `<option value="${esc(d.id)}">${esc(displayName(d))}</option>`).join('')}</select></label><label>${tr('Новый офис', 'New office')}<select name="room" aria-label="${tr('Новый офис', 'New office')}">${targets.map(r => `<option value="${esc(r.id)}">${esc(r.title)}</option>`).join('')}</select></label>`, data => ({body:{id:data.get('id'),room:data.get('room')},message:tr("Демон переселён. Его новое место сохранено.", "Daemon moved. Its new seat is saved.")}));
}
const roomGrid = $('buildingRooms');
function endRoomDrag() {
  buildingView.dragging = null;
  roomGrid.querySelectorAll('.drop-target, .dragging').forEach(el => el.classList.remove('drop-target','dragging'));
  renderBuilding();
}
let roomPointer = null;
roomGrid.addEventListener('pointerdown', e => {
  const resident = e.target.closest('[data-resident]');
  // Touch keeps native scrolling. The inline ‘Переселить’ form works on touch and keyboards.
  if (!resident || e.pointerType === 'touch' || e.button !== 0 || buildingView.busy || buildingView.editing) return;
  roomPointer = {id:resident.dataset.resident, pointer:e.pointerId, x:e.clientX, y:e.clientY, node:resident};
  resident.setPointerCapture(e.pointerId);
});
roomGrid.addEventListener('pointermove', e => {
  if (!roomPointer || roomPointer.pointer !== e.pointerId) return;
  if (!buildingView.dragging && Math.hypot(e.clientX-roomPointer.x,e.clientY-roomPointer.y) < 6) return;
  e.preventDefault();
  buildingView.dragging = roomPointer.id;
  roomPointer.node.classList.add('dragging');
  const target = document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-drop-room]');
  roomGrid.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
  if (target) target.classList.add('drop-target');
  const scrollBox = $('mainContent') || $('building'), bounds = scrollBox.getBoundingClientRect();
  if (e.clientY < bounds.top + 70) scrollBox.scrollTop -= 24;
  else if (e.clientY > Math.min(bounds.bottom,window.innerHeight) - 70) scrollBox.scrollTop += 24;
});
function finishRoomPointer(e, cancelled=false) {
  if (!roomPointer || roomPointer.pointer !== e.pointerId) return;
  const id = buildingView.dragging;
  const target = document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-drop-room]');
  const room = target?.dataset.dropRoom;
  const node = roomPointer.node; roomPointer = null;
  if (node.hasPointerCapture(e.pointerId)) node.releasePointerCapture(e.pointerId);
  if (id) { buildingView.suppressClickUntil = Date.now()+350; endRoomDrag(); }
  const demon = lastSnapshot.daemons.find(d => d.id === id);
  if (!cancelled && id && room && demon && demon.office_id !== room) roomAction({id,room}, tr("Демон переселён", "Daemon moved"));
}
roomGrid.addEventListener('pointerup', e => finishRoomPointer(e));
roomGrid.addEventListener('pointercancel', e => finishRoomPointer(e,true));
roomGrid.addEventListener('lostpointercapture', e => { if (roomPointer) finishRoomPointer(e,true); });

// Palette substitution on individual animation frames. Bounded cache, no atlas copies.
const frameLooks = new Map(), thumbLooks = new Map(), imageKeys = new WeakMap();
let nextImageKey = 0;
function clothingPixel(r,g,b,id) {
  const max = Math.max(r,g,b), min = Math.min(r,g,b), delta = max-min;
  if (max < 40 || max > 245) return false;
  if (id === 'worker_black_charcoal') return delta < 18 && max < 100;
  if (!delta || delta / max < .25) return false;
  let h = max === r ? ((g-b)/delta + 6)%6 : max === g ? (b-r)/delta + 2 : (r-g)/delta + 4;
  h /= 6;
  if (id === 'worker_orange_yellow') return h > .105 && h < .19;
  if (id === 'worker_brown_red') return h < .035 || h > .95;
  if (id === 'worker_brown_green') return h > .22 && h < .48;
  if (id === 'worker_dark_purple') return h > .66 && h < .91;
  return h > .52 && h < .72;
}
function appearanceFrame(img,sx,sy,sw,sh,character,variant) {
  if (!variant) return null;
  if (!imageKeys.has(img)) imageKeys.set(img, ++nextImageKey);
  const key = [imageKeys.get(img),sx,sy,sw,sh,character,variant].join(':');
  if (frameLooks.has(key)) { const c=frameLooks.get(key); frameLooks.delete(key); frameLooks.set(key,c); return c; }
  const c = document.createElement('canvas'); c.width=sw; c.height=sh;
  const g=c.getContext('2d', {willReadFrequently:true}); g.drawImage(img,sx,sy,sw,sh,0,0,sw,sh);
  const pixels=g.getImageData(0,0,sw,sh), p=pixels.data;
  const hex=LOOK_COLORS[variant] || LOOK_COLORS[0], rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16));
  for(let i=0;i<p.length;i+=4) if(p[i+3] && clothingPixel(p[i],p[i+1],p[i+2],character)) {
    const light=Math.max(p[i],p[i+1],p[i+2])/210;
    for(let n=0;n<3;n++) p[i+n]=Math.min(255,Math.round(rgb[n]*light));
  }
  g.putImageData(pixels,0,0); frameLooks.set(key,c);
  if(frameLooks.size>256) frameLooks.delete(frameLooks.keys().next().value);
  return c;
}
function appearanceThumb(d) {
  const ch=office.chars[d.character];
  if(!ch) return '';
  const v=d.appearance || 0, key=ch.id+':'+v;
  if(thumbLooks.has(key)) return thumbLooks.get(key);
  const a=ch.anims.idle_down || Object.values(ch.anims)[0], cell=a.cells[0];
  const c=appearanceFrame(ch.img,(cell.col||0)*ch.fw+28,(cell.row||0)*ch.fh+12,72,104,ch.id,v);
  const url=c ? c.toDataURL() : office.thumbs[ch.id];
  thumbLooks.set(key,url); return url;
}
async function chooseAppearance(id,variant) {
  try {
    const res=await (await fetch('/api/characters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,variant})})).json();
    if(res.error) throw new Error(res.error);
    const d=lastSnapshot.daemons.find(x=>x.id===id); if(d) d.appearance=variant;
    renderCharPicker(); renderBuilding(); refreshDrawer(false);
  } catch(e) { const box=$('drawerChars'); box.insertAdjacentHTML('beforeend',`<p class="warn">${esc(e.message)}</p>`); }
}

// Create the building together with its first office, using a persistent address.
$('officeCreateOpen')?.addEventListener('click', () => {
  const form = $('officeCreateForm');
  if (!form.hidden) { $('officeCreateCancel').click(); return; }
  const buildings = cityLayout(lastSnapshot.offices || []);
  $('officeCreateBuilding').innerHTML = buildings.map(b => `<option value="${b.number}" ${b.rooms.length >= CITY_FLOORS ? 'disabled' : ''}>${esc(b.title)} · ${b.rooms.length}/${CITY_FLOORS}</option>`).join('') + `<option value="new">${tr('Новый корпус', 'New building')}</option>`;
  $('officeCreateBuilding').value = 'new';
  $('officeCreateStatus').textContent = '';
  form.hidden = false;
  $('officeCreateOpen').setAttribute('aria-expanded', 'true');
  $('officeCreateName').focus();
});
$('officeCreateCancel')?.addEventListener('click', () => {
  if (buildingView.busy) return;
  const form = $('officeCreateForm');
  form.reset(); markFormClean(form); form.hidden = true;
  $('officeCreateOpen').setAttribute('aria-expanded', 'false');
  $('officeCreateOpen').focus();
});
$('officeCreateForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  if (buildingView.busy) return;
  const form = event.currentTarget, choice = $('officeCreateBuilding').value;
  const name = $('officeCreateName').value.trim();
  if (!name) { $('officeCreateName').focus(); return; }
  const controls = [...form.querySelectorAll('input,select,button')];
  controls.forEach(el => el.disabled = true);
  $('officeCreateStatus').textContent = tr('Создаём…', 'Creating…');
  const ok = await roomAction({action:'create', name, building:choice === 'new' ? 'new' : Number(choice)}, tr('Офис создан. Теперь можно переселить в него демонов.', 'Office created. You can now move daemons into it.'));
  controls.forEach(el => el.disabled = false);
  if (ok) {
    $('officeCreateCancel').click();
    $('officeCreateStatus').textContent = '';
  } else $('officeCreateStatus').textContent = $('buildingStatus').textContent;
});
