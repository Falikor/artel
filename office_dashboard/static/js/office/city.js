'use strict';
/* Offline orthographic 3D scene. Geometry, picking and animation share one camera.
   The city is decorative; room selection always uses the real office catalogue. */
const city = {
  canvas: $('cityCanvas'), rooms: [], eligible: new Set(), selected: null,
  buildings: [], scenery: [], focus: null, faces: [], time: 8, last: 0, painted: 0, dirty: true, visible: true,
  width: 0, height: 0, dpr: 1, theme: '', previewKey: '', closeUntil: 0, labelKey: '', labels: [], naming: false, savingName: false,
  view: {zoom:1,x:0,y:0}, dragging: false, suppressClickUntil: 0,
};
function cityContains(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > point[1]) !== (b[1] > point[1]) && point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}
function cityRoomMatches(room) {
  const ds = lastSnapshot.daemons.filter(d => d.office_id === room.id);
  return ds.some(d => matchesDemon(d, room)) || (!ds.length && rosterFilter.status === 'all' &&
    (!rosterFilter.query || `${room.title} ${room.project || ''} ${cityRoomBuildingTitle(room)}`.toLocaleLowerCase().includes(rosterFilter.query)));
}
function renderCityRooms(rooms) {
  city.rooms = [...rooms].sort((a,b) => (a.building_level || 0) - (b.building_level || 0) || a.id.localeCompare(b.id));
  city.buildings = cityLayout(city.rooms);
  city.scenery = citySurroundings(city.buildings);
  if (city.focus!==null && !city.buildings.some(b=>b.number===city.focus)) {city.focus=null;cityResetView();}
  city.eligible = new Set(rooms.filter(cityRoomMatches).map(r => r.id));
  if (!city.eligible.has(city.selected)) city.selected = null;
  const nav = $('cityFloors'), active = document.activeElement?.dataset?.cityFloor;
  const html = rooms.filter(r => city.eligible.has(r.id)).map(r => {
    const ds = lastSnapshot.daemons.filter(d => d.office_id === r.id), stats = roomStats(ds);
    return `<button type="button" class="city-floor" data-city-floor="${esc(r.id)}" aria-controls="cityPreview" aria-expanded="${r.id === city.selected}" aria-pressed="${r.id === city.selected}"><span class="city-floor-address">${esc(cityAddressLabel(r,city.rooms.indexOf(r)+1))}</span><span>${esc(r.title)}</span>${stats.bad ? `<small aria-label="${tr('Требуют внимания:', 'Needs attention:')} ${stats.bad}">! ${stats.bad}</small>` : ''}</button>`;
  }).join('');
  if (nav.innerHTML !== html) {
    nav.innerHTML = html;
    if (active) [...nav.querySelectorAll('button')].find(b => b.dataset.cityFloor === active)?.focus({preventScroll:true});
  }
  $('cityHint').textContent = !rooms.length ? tr("Офисы появятся при подключении демонов", "Offices appear when daemons connect") : !city.eligible.size ? tr("По этому фильтру нет офисов", "No offices match this filter") : tr("Наведите на этаж, чтобы заглянуть внутрь", "Hover over a floor to look inside");
  renderCityBuildings(); cityPreview(); city.dirty = true;
}
function renderCityBuildings() {
  const nav=$('cityBuildings'), active=nav.contains(document.activeElement)?document.activeElement?.dataset?.cityBuilding:null;
  const html=`<button type="button" class="btn" data-city-building="all" aria-pressed="${city.focus===null}">${tr('Весь квартал', 'Entire district')}</button>`+
    city.buildings.map(b=>`<button type="button" class="btn" data-city-building="${b.number}" aria-pressed="${city.focus===b.number}"><b>${esc(b.title)}</b><span>${b.title!==`${tr('Корпус', 'Building')} ${b.number}`?`№${b.number} · `:''}${b.rooms.length}/16 ${tr('офисов', 'offices')}</span></button>`).join('');
  if(nav.innerHTML!==html) {
    nav.innerHTML=html;
    if(active)[...nav.querySelectorAll('button')].find(b=>b.dataset.cityBuilding===active)?.focus({preventScroll:true});
  }
  nav.hidden=city.buildings.length<2 && city.focus===null;
  $('cityRenameOpen').disabled=!city.buildings.length||city.savingName;
  const count=city.buildings.length, p=cityPopulation(count);
  const word=count%100>=11&&count%100<=14?'корпусов':count%10===1?'корпус':count%10>=2&&count%10<=4?'корпуса':'корпусов';
  $('cityDistrictSummary').textContent=city.focus?`${city.buildings.find(b=>b.number===city.focus)?.title || `${tr('Корпус', 'Building')} ${city.focus}`} · ${tr('до 16 офисов', 'up to 16 offices')}`:count>1?tr(`${count} ${word} · магазинов и кафе: ${p.shops} · школ: ${p.schools}`, `${count} buildings · shops and cafes: ${p.shops} · schools: ${p.schools}`):tr("Каждый этаж — ваша команда", "A home for each team");
}
function cityOpenNameEditor() {
  if(!city.buildings.length||city.savingName)return;
  city.naming=true;
  $('cityNameBuilding').innerHTML=city.buildings.map(b=>`<option value="${b.number}">${tr('Корпус', 'Building')} ${b.number}${b.title!==`${tr('Корпус', 'Building')} ${b.number}`?` — ${esc(b.title)}`:''}</option>`).join('');
  $('cityNameBuilding').value=String(city.focus || city.buildings[0].number);
  cityNameTargetChanged();
  $('cityNameStatus').textContent='';
  $('cityNameForm').hidden=false;$('cityRenameOpen').setAttribute('aria-expanded','true');
  $('cityNameInput').focus();$('cityNameInput').select();
}
function cityNameTargetChanged() {
  const b=city.buildings.find(b=>b.number===Number($('cityNameBuilding').value));
  $('cityNameInput').value=b?.title || '';
  markFormClean($('cityNameForm'));
}
function cityCloseNameEditor() {
  if(city.savingName)return;
  markFormClean($('cityNameForm'));
  city.naming=false;$('cityNameForm').hidden=true;$('cityRenameOpen').setAttribute('aria-expanded','false');
  $('cityRenameOpen').focus({preventScroll:true});
}
async function citySaveName(e) {
  e.preventDefault();
  if(city.savingName)return;
  const building=Number($('cityNameBuilding').value), name=$('cityNameInput').value.trim();
  const status=$('cityNameStatus');
  if(!name || Array.from(name).length>60 || /[\p{C}\p{Zl}\p{Zp}]/u.test(name)) {
    status.textContent=tr("Введите название от 1 до 60 символов, без переносов строк.", "Enter a name of 1–60 characters, without line breaks.");return;
  }
  city.savingName=true;status.textContent=tr("Сохраняем название…", "Saving name…");
  const controls=['cityNameBuilding','cityNameInput','cityNameSave','cityNameCancel','cityRenameOpen'];
  controls.forEach(id=>$(id).disabled=true);$('cityNameForm').setAttribute('aria-busy','true');
  let saved=false;
  try {
    const response=await fetch('/api/buildings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'rename',building,name})});
    const snap=await response.json();
    if(!response.ok || snap.error)throw new Error(translateServerMessage(snap.error) || tr("Не удалось сохранить название. Попробуйте ещё раз.", "Could not save the name. Try again."));
    saved=true;markFormClean($('cityNameForm'));
    try { apply(snap);status.textContent=tr("Название корпуса сохранено", "Building name saved"); }
    catch (_) { status.textContent=tr("Название сохранено. Обновите страницу, чтобы увидеть изменения.", "Name saved. Reload the page to see the changes."); }
  } catch (error) { status.textContent=translateServerMessage(error.message) || tr("Нет связи с сервером. Попробуйте ещё раз.", "Cannot reach the server. Try again."); }
  finally {
    city.savingName=false;controls.forEach(id=>$(id).disabled=false);$('cityNameForm').setAttribute('aria-busy','false');
    if(saved)cityCloseNameEditor();
    $('cityRenameOpen').disabled=!city.buildings.length;
  }
}
$('cityRenameOpen').addEventListener('click',()=>city.naming?cityCloseNameEditor():cityOpenNameEditor());
$('cityNameBuilding').addEventListener('change',cityNameTargetChanged);
$('cityNameCancel').addEventListener('click',cityCloseNameEditor);
$('cityNameForm').addEventListener('submit',citySaveName);
$('cityNameForm').addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();cityCloseNameEditor();}});
function cityFocusClick(e) {
  if(cityIgnoreClick(e))return;
  const value=e.target.closest('[data-city-building]')?.dataset.cityBuilding;
  if(value===undefined)return;
  city.focus=value==='all'?null:Number(value);
  cityResetView();
  if(city.selected && city.focus!==null && cityAddress(city.rooms.find(r=>r.id===city.selected)).building!==city.focus)citySelect(null);
  renderCityBuildings(); city.dirty=true;
}
$('cityBuildings').addEventListener('click',cityFocusClick);
$('cityLabels').addEventListener('click',cityFocusClick);
function renderCityLabels(camera,buildings) {
  const key=JSON.stringify([city.width,city.height,city.focus,camera.view,buildings.map(b=>[b.number,b.floors,b.title])]);
  if(key===city.labelKey)return;
  city.labels=cityLabels(camera,buildings,city.focus);city.labelKey=key;
  const host=$('cityLabels'), active=host.contains(document.activeElement)?document.activeElement.dataset.cityBuilding:null;
  host.innerHTML=city.labels.map(label=>`<button type="button" class="city-building-label" data-city-building="${label.number}" aria-label="${tr('Приблизить корпус', 'Zoom to building')} ${label.number}: ${esc(label.text)}" title="${esc(label.text)} · ${tr('корпус', 'building')} ${label.number}" aria-pressed="${city.focus===label.number}" style="left:${label.x}px;top:${label.y}px;width:${label.w}px;height:${label.h}px">${esc(label.text)}</button>`).join('');
  if(active)[...host.querySelectorAll('button')].find(b=>b.dataset.cityBuilding===active)?.focus({preventScroll:true});
}
function citySelect(id, focusBuilding=false) {
  if (id !== null && !city.eligible.has(id)) return;
  if(focusBuilding && id) {city.focus=cityAddress(city.rooms.find(r=>r.id===id)).building;cityResetView();renderCityBuildings();city.dirty=true;}
  if (city.selected === id) return;
  city.selected = id; city.dirty = true;
  for (const b of $('cityFloors').querySelectorAll('button')) {
    b.setAttribute('aria-pressed', String(b.dataset.cityFloor === id));
    b.setAttribute('aria-expanded', String(b.dataset.cityFloor === id));
  }
  cityPreview();
}
function cityPreview() {
  const box = $('cityPreview'), room = city.rooms.find(r => r.id === city.selected);
  if (!room) { box.hidden = true; city.previewKey = ''; return; }
  const ds = lastSnapshot.daemons.filter(d => d.office_id === room.id), counts = roomStats(ds);
  const picture = office.plate?.src;
  const html = `<div class="city-preview-head"><div><small>${esc(cityAddressLabel(room,city.rooms.indexOf(room)+1))}</small><h3>${esc(room.title)}</h3></div><button type="button" class="close" data-city-action="close" aria-label="${tr('Закрыть предпросмотр', 'Close preview')}">×</button></div>
    <p class="city-preview-meta">${tr(`${ds.length} из ${room.capacity} мест · ${counts.busy} работают`, `${ds.length} of ${room.capacity} seats · ${counts.busy} working`)}${counts.bad ? tr(` · ${counts.bad} требуют внимания`, ` · ${counts.bad} need attention`) : ''}</p>
    <div class="city-office-image" role="img" aria-label="${tr('Офис', 'Office')} ${esc(room.title)}. ${tr('Закреплённые места демонов.', 'Assigned daemon seats.')}">${picture ? `<img src="${esc(picture)}" alt="" draggable="false">${ds.map(d => {
      const seat = SEATS[d.office_slot], thumb = appearanceThumb(d);
      return seat && thumb ? `<img class="preview-demon" src="${thumb}" alt="" draggable="false" style="left:${seat.pos[0]/PLATE*100}%;top:${seat.pos[1]/PLATE*100}%">` : '';
    }).join('')}` : `<span class="city-art-loading">${tr('Оформление офиса загружается…', 'Loading office artwork…')}</span>`}</div>
    <div class="city-preview-actions"><button type="button" class="btn primary" data-city-action="open">${tr('Войти в офис', 'Enter office')} →</button><button type="button" class="btn" data-city-action="manage">${tr('Рассадка', 'Seating')}</button></div>`;
  if (city.previewKey !== html) {
    const focused = box.contains(document.activeElement) ? document.activeElement.dataset.cityAction : null;
    const scroll = box.scrollTop;
    box.innerHTML = html; city.previewKey = html; box.scrollTop = scroll;
    if (focused) box.querySelector(`[data-city-action="${focused}"]`)?.focus({preventScroll:true});
  }
  box.hidden = false;
}
$('cityFloors').addEventListener('click', e => {
  const button = e.target.closest('[data-city-floor]');
  if (button) {
    citySelect(button.dataset.cityFloor,true);
    if (e.detail === 0) $('cityPreview').querySelector('[data-city-action="open"]')?.focus();
  }
});
$('cityFloors').addEventListener('keydown', e => {
  const buttons = [...$('cityFloors').querySelectorAll('button')], i = buttons.indexOf(e.target);
  if (i < 0 || !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key)) return;
  e.preventDefault();
  const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length-1 :
    (i + (['ArrowLeft','ArrowUp'].includes(e.key) ? -1 : 1) + buttons.length) % buttons.length;
  buttons[next].focus(); citySelect(buttons[next].dataset.cityFloor,true);
});
$('cityPreview').addEventListener('click', e => {
  const action = e.target.closest('[data-city-action]')?.dataset.cityAction;
  if (action === 'close') {
    const id = city.selected; citySelect(null); city.closeUntil = performance.now() + 400;
    [...$('cityFloors').querySelectorAll('button')].find(b => b.dataset.cityFloor === id)?.focus({preventScroll:true});
  } else if (action === 'open') {
    openOffice(city.selected); $('backBuilding')?.focus({preventScroll:true});
  }
  else if (action === 'manage') {
    $('officeDirectory').open = true;
    const card = [...$('buildingRooms').querySelectorAll('[data-drop-room]')].find(el => el.dataset.dropRoom === city.selected);
    card?.scrollIntoView({block:'nearest', behavior:officeMotionPaused() ? 'instant' : 'smooth'});
    card?.querySelector('[data-move-room]:not(:disabled),[data-rename-room]')?.focus({preventScroll:true});
  }
});
$('cityStage').addEventListener('keydown', e => {
  if (e.key === 'Escape' && city.selected) {
    const id = city.selected; citySelect(null);
    [...$('cityFloors').querySelectorAll('button')].find(b => b.dataset.cityFloor === id)?.focus({preventScroll:true});
  }
});
$('cityMotion').addEventListener('click', () => {
  social.paused = !social.paused; storage.set('artel-motion-paused', social.paused);
  updateMotionControl(); city.dirty = true;
});
function cityPick(e) {
  const rect = city.canvas.getBoundingClientRect(), point = [e.clientX-rect.left, e.clientY-rect.top];
  return [...city.faces].reverse().find(face => city.eligible.has(face.id) && cityContains(point, face.points))?.id || null;
}
city.canvas.addEventListener('pointermove', e => {
  if (e.pointerType === 'touch' || city.dragging) return;
  const id = cityPick(e); city.canvas.style.cursor = id ? 'pointer' : '';
  // Retain the preview while crossing the gap between the facade and its controls.
  if (id && performance.now() > city.closeUntil) citySelect(id);
});
city.canvas.addEventListener('click', e => { if(cityIgnoreClick(e))return;const id = cityPick(e); if (id) citySelect(id); });

function drawCity() {
  const canvas = city.canvas, g = canvas.getContext('2d');
  if (!g) return;
  const w = city.width, h = city.height, dark = city.theme === 'dark';
  const buildings=city.buildings.length?city.buildings:[{number:1,x:0,y:0,near:false,rooms:[],floors:1}];
  const scenery=city.buildings.length?city.scenery:citySurroundings(buildings);
  const c=cityViewCamera(cityCamera(w,h,buildings,scenery,city.focus),city.view);
  city.view=c.view;
  let origin=[0,0], zScale=1;
  const p=(x,y,z=0)=>c.project(x+origin[0],y+origin[1],z*zScale);
  const visible=(x,y,bw,bd,bh=0)=>{
    const points=cityBounds(x,y,bw,bd,bh), base=c.project(0,0);
    const xs=points.map(a=>base[0]+a[0]*c.scale),ys=points.map(a=>base[1]+a[1]*c.scale);
    return Math.max(...xs)>-30&&Math.min(...xs)<w+30&&Math.max(...ys)>-30&&Math.min(...ys)<h+30;
  };
  const color = dark ? {
    sky:'#17282f', ground:'#23383d', paving:'#34494c', curb:'#536466', road:'#17272e', roadLine:'#60797d',
    wall:'#4b6568', side:'#344e53', top:'#849895', edge:'#a6bbb3', glass:'#1a3e46', glassSide:'#17323b', lit:'#acbc91',
    metal:'#23484b', accent:'#83e3ce', ink:'#ecf9ed', shadow:'#081b2660', tree:'#386965', treeLight:'#568577', distant:'#2d4148',
  } : {
    sky:'#e0eaeb', ground:'#d2dfdc', paving:'#eff0e7', curb:'#b7c7c3', road:'#859a9e', roadLine:'#e5eeea',
    wall:'#efede0', side:'#c2cec7', top:'#f8f4e6', edge:'#f6f4df', glass:'#426b70', glassSide:'#33565f', lit:'#c9dcc5',
    metal:'#315656', accent:'#087d70', ink:'#173e40', shadow:'#36545324', tree:'#3e7966', treeLight:'#6a9a7b', distant:'#b1c7c8',
  };
  g.setTransform(city.dpr,0,0,city.dpr,0,0); g.clearRect(0,0,w,h);
  g.fillStyle = color.ground; g.fillRect(0,0,w,h);
  const path = (points, fill, stroke, width=1) => {
    g.beginPath(); points.forEach((a,i) => i ? g.lineTo(...a) : g.moveTo(...a)); g.closePath();
    if (fill) { g.fillStyle=fill; g.fill(); }
    if (stroke) { g.strokeStyle=stroke; g.lineWidth=width; g.lineJoin='round'; g.stroke(); }
  };
  const poly = (points, fill, stroke, width=1) => path(points.map(a => p(...a)),fill,stroke,width);
  const box = (x,y,z,bw,bd,bh,front=color.wall,side=color.side,top=color.top) => {
    poly([[x,y+bd,z],[x+bw,y+bd,z],[x+bw,y+bd,z+bh],[x,y+bd,z+bh]],front);
    poly([[x+bw,y,z],[x+bw,y+bd,z],[x+bw,y+bd,z+bh],[x+bw,y,z+bh]],side);
    poly([[x,y,z+bh],[x+bw,y,z+bh],[x+bw,y+bd,z+bh],[x,y+bd,z+bh]],top);
  };
  const flat = (x,y,bw,bd,z,fill) => poly([[x,y,z],[x+bw,y,z],[x+bw,y+bd,z],[x,y+bd,z]],fill);
  const line = (a,b,stroke,width=1) => { g.beginPath();g.moveTo(...p(...a));g.lineTo(...p(...b));g.strokeStyle=stroke;g.lineWidth=width;g.stroke(); };
  const frontText = (text,x,y,z,size,fill) => {
    const q=p(x,y,z); g.save(); g.transform(.94*c.scale,.23*c.scale,0,c.scale*zScale,...q);
    g.font=`600 ${size}px system-ui, sans-serif`;g.fillStyle=fill;g.fillText(text,0,0);g.restore();
  };
  const shadow = (x,y,bw,bd,height) => poly([[x,y,0],[x+bw,y,0],[x+bw+height*.48,y+bd+height*.2,0],[x+height*.48,y+bd+height*.2,0]],color.shadow);
  // Street and sidewalks are a continuous plane, including the foreground crossing.
  const streetLeft=Math.min(...buildings.map(b=>b.x))-1300, streetRight=Math.max(...buildings.map(b=>b.x))+1400, streetWidth=streetRight-streetLeft;
  flat(streetLeft,206,streetWidth,72,-2,color.curb);
  flat(streetLeft,204,streetWidth,65,0,color.paving);
  flat(streetLeft,280,streetWidth,128,-2,color.road);
  flat(streetLeft,408,streetWidth,67,-2,color.curb);
  flat(streetLeft,414,streetWidth,58,0,color.paving);
  for(let x=streetLeft;x<streetRight;x+=54) flat(x,342,26,2,-1,color.roadLine);
  for(const b of buildings)for(let y=288;y<406;y+=15)flat(b.x+85,y,34,7,-1,color.roadLine);
  for(let x=streetLeft;x<streetRight;x+=54) line([x,209,.2],[x,263,.2],dark?'#3e5456':'#d6dfd6',.7);
  for(const b of buildings) {
    flat(b.x-29,b.y-25,282,220,0,color.paving);
    if(b.near)flat(b.x+235,472,18,b.y-472+50,.1,color.paving);
    else flat(b.x+101,b.y+120,22,84,.1,color.paving);
    shadow(b.x,b.y,220,120,(56+b.floors*62)*CITY_HEIGHT);
  }
  const objects = [];
  const add = (depth, draw) => objects.push({depth,draw});
  // Houses, shops and schools grow with the number of office buildings.
  for(const s of scenery) {
    if(!visible(s.x,s.y,s.w,s.d+(s.kind==='school'?82:0),s.h+28))continue;
    // Each building has a real lot and a pavement connection, not a floating box.
    flat(s.x-10,s.y-10,s.w+20,s.d+(s.kind==='school'?100:20),0,dark?'#304941':'#c2d6bd');
    if(s.y+s.d<204)flat(s.x+s.w/2-7,s.y+s.d,14,204-s.y-s.d,.1,color.paving);
    else if(s.y>472)flat(s.x+s.w/2-7,472,14,s.y-472,.1,color.paving);
    shadow(s.x,s.y,s.w,s.d,s.h);
    add(s.x+s.y+s.d,()=>{
      const front=dark?'#3b555b':'#c6d4cd', side=dark?'#2a4149':'#9fb9b7';
      box(s.x,s.y,0,s.w,s.d,s.h,front,side,dark?'#5b716e':'#e0e6d9');
      if(s.kind==='house') {
        for(let z=14;z<s.h-12;z+=25)for(let dx=12;dx<s.w-15;dx+=24)
          poly([[s.x+dx,s.y+s.d+.1,z],[s.x+dx+11,s.y+s.d+.1,z],[s.x+dx+11,s.y+s.d+.1,z+14],[s.x+dx,s.y+s.d+.1,z+14]],dark?'#829b8c':'#5e8586');
        poly([[s.x-5,s.y+s.d+5,s.h],[s.x+s.w/2,s.y+s.d+5,s.h+24],[s.x+s.w+5,s.y+s.d+5,s.h]],dark?'#5e6864':'#ad9b83');
        poly([[s.x+s.w/2,s.y-4,s.h+24],[s.x+s.w/2,s.y+s.d+5,s.h+24],[s.x+s.w+5,s.y+s.d+5,s.h],[s.x+s.w+5,s.y-4,s.h]],dark?'#465c60':'#839f9b');
      } else if(s.kind==='shop') {
        for(let dx=7;dx<s.w-8;dx+=27)poly([[s.x+dx,s.y+s.d+.1,5],[s.x+dx+21,s.y+s.d+.1,5],[s.x+dx+21,s.y+s.d+.1,26],[s.x+dx,s.y+s.d+.1,26]],color.glass);
        for(let dx=0;dx<s.w;dx+=12)poly([[s.x+dx,s.y+s.d,30],[s.x+Math.min(s.w,dx+12),s.y+s.d,30],[s.x+Math.min(s.w,dx+12),s.y+s.d+14,24],[s.x+dx,s.y+s.d+14,24]],dx%24?color.edge:color.tree);
        frontText(s.title,s.x+8,s.y+s.d+1,s.h-4,9,color.ink);
      } else {
        for(let dx=10;dx<s.w-12;dx+=25)for(const z of [12,36])poly([[s.x+dx,s.y+s.d+.1,z],[s.x+dx+14,s.y+s.d+.1,z],[s.x+dx+14,s.y+s.d+.1,z+17],[s.x+dx,s.y+s.d+.1,z+17]],color.glass);
        box(s.x+s.w/2-21,s.y+s.d,0,42,12,48,color.wall,color.side,color.top);
        poly([[s.x+s.w/2-30,s.y+s.d+13,48],[s.x+s.w/2,s.y+s.d+13,72],[s.x+s.w/2+30,s.y+s.d+13,48]],color.top);
        frontText(tr("ШКОЛА", "SCHOOL"),s.x+s.w/2-18,s.y+s.d+13,37,9,color.ink);
        box(s.x+s.w/2-9,s.y+s.d+13,0,18,1,25,color.glass);
        // Flag and playground beside the school, with a basketball hoop.
        box(s.x-16,s.y+s.d,0,2,2,68,color.metal);
        poly([[s.x-14,s.y+s.d,68],[s.x+9,s.y+s.d,68],[s.x+9,s.y+s.d,55],[s.x-14,s.y+s.d,55]],color.accent);
        flat(s.x,s.y+s.d+30,s.w,48,0,dark?'#355b53':'#9ebca1');
        line([s.x+8,s.y+s.d+54,.3],[s.x+s.w-8,s.y+s.d+54,.3],color.edge,1);
        box(s.x+8,s.y+s.d+72,0,2,2,30,color.metal);box(s.x+3,s.y+s.d+72,30,14,2,10,color.edge);
      }
      if(s.kind!=='house' && c.scale>.5) {
        const at=p(s.x+s.w/2,s.y+s.d/2,s.h+26), labelWidth=s.title.length*7+16;
        g.font='500 11px system-ui, sans-serif';g.textAlign='center';
        g.fillStyle=dark?'#17282fe8':'#e0eaebed';g.fillRect(at[0]-labelWidth/2,at[1]-12,labelWidth,19);
        g.fillStyle=color.ink;g.fillText(s.title,at[0],at[1]+1);g.textAlign='start';
      }
    });
  }
  const tree = (x,y,size=1) => {
    if(!visible(x-22,y-22,44,44,60*size))return;
    shadow(x-12,y-12,28,20,35*size);
    add(x+y+10, () => {
      box(x-10,y-10,0,23,23,5,dark?'#47605b':'#bcc8b7',color.side,color.paving);
      box(x,y,5,4,4,25*size,'#796d54','#4a554b','#9d9371');
      const z=28*size, r=19*size;
      poly([[x-r,y,z],[x,y+r,z],[x,y,z+r*1.4]],color.tree);
      poly([[x,y+r,z],[x+r,y,z],[x,y,z+r*1.4]],color.treeLight);
      poly([[x-r,y,z],[x,y-r,z],[x,y,z+r*1.4]],dark?'#315754':'#538b6f');
      poly([[x,y-r,z],[x+r,y,z],[x,y,z+r*1.4]],dark?'#49766b':'#7ca67e');
    });
  };
  for(const b of buildings) {tree(b.x-76,b.y+115,1.15);tree(b.x+260,b.y+117,1.1);tree(b.x-218,b.near?446:234,.95);}
  const lamp = (x,y) => {
    if(!visible(x-3,y-2,23,8,60))return;
    add(x+y, () => {
    box(x,y,0,3,3,57,color.metal,color.metal,color.edge);
    box(x-3,y-2,55,20,6,3,color.metal,color.metal,color.edge);
    flat(x+8,y-2,8,6,54,dark?'#f4e3b0':'#e8e7d6');
    if(dark) { const q=p(x+12,y,53);g.beginPath();g.arc(q[0],q[1],6*c.scale,0,Math.PI*2);g.fillStyle='#f0d89725';g.fill(); }
    });
  };
  for(const b of buildings) {lamp(b.x-130,b.near?436:251);lamp(b.x+300,b.near?436:251);}
  add(-20+223,() => { box(-52,225,0,3,12,10,color.metal);box(-18,225,0,3,12,10,color.metal);box(-57,221,10,45,17,3,'#ad936a','#7b745b','#c4ad86');box(-57,221,13,45,3,14,'#ad936a','#7b745b','#c4ad86'); });
  city.faces=[];
  for(const building of buildings) {
  if(!visible(building.x,building.y,232,132,(92+building.floors*62)*CITY_HEIGHT))continue;
  const levels=Array.from({length:building.floors},(_,i)=>building.rooms.find(e=>e.floor===i+1)?.room||{id:null,title:tr("Свободный этаж", "Vacant floor")});
  add(building.x+building.y+220, () => {
    origin=[building.x,building.y];zScale=CITY_HEIGHT;
    // Foundation, glazed lobby and cantilever canopy.
    box(-5,-5,0,230,130,6,color.side,color.metal,color.paving);
    box(0,0,6,220,120,50,color.wall,color.side,color.top);
    for(let x=12;x<210;x+=34) poly([[x,120.2,10],[x+26,120.2,10],[x+26,120.2,42],[x,120.2,42]],color.glass);
    poly([[91,120.5,6],[133,120.5,6],[133,120.5,43],[91,120.5,43]],dark?'#99b998':'#315d60');
    line([112,121,6],[112,121,43],color.edge,1); line([116,122,21],[116,122,29],color.edge,1.2);
    box(79,116,42,68,23,4,color.metal,color.metal,color.edge);
    if(building.near) {
      // The street-facing approach enters the visible side lobby, not the back wall.
      const entrance=cityEntrance(building), ey=entrance.y-building.y;
      poly([[221,ey-15,6],[221,ey+15,6],[221,ey+15,43],[221,ey-15,43]],dark?'#99b998':'#315d60');
      line([222,ey,6],[222,ey,43],color.edge,1);
      box(216,ey-23,43,23,46,4,color.metal,color.metal,color.edge);
    }
    // Office floors: real catalogue order, permanent level numbers, two selectable faces.
    levels.forEach((room,index) => {
      const z=56+index*62, selected=room.id && city.selected===room.id;
      const eligible = !room.id || city.eligible.has(room.id);
      g.globalAlpha=eligible ? 1 : .46;
      box(0,0,z,220,120,62,color.wall,color.side,color.top);
      const front=[[0,120.5,z+2],[220,120.5,z+2],[220,120.5,z+60],[0,120.5,z+60]];
      const side=[[220.5,0,z+2],[220.5,120,z+2],[220.5,120,z+60],[220.5,0,z+60]];
      if(selected) { poly(front,dark?'#4b8b7d':'#b2dacc');poly(side,dark?'#367166':'#8fbcaf'); }
      for(let x=34;x<205;x+=38) {
        poly([[x,121,z+15],[x+29,121,z+15],[x+29,121,z+49],[x,121,z+49]],color.glass);
        poly([[x+2,121.2,z+17],[x+13,121.2,z+17],[x+13,121.2,z+47],[x+2,121.2,z+47]],(index+Math.floor(x/38))%3===0?color.lit:(dark?'#38606a':'#7b9d98'));
        line([x+15,121.4,z+15],[x+15,121.4,z+49],color.metal,.9*c.scale);
        line([x,121.4,z+28],[x+29,121.4,z+28],color.metal,.8*c.scale);
        // Desks silhouetted behind the windows make the facade read as occupied offices.
        poly([[x+4,121.5,z+18],[x+21,121.5,z+18],[x+21,121.5,z+21],[x+4,121.5,z+21]],color.metal);
      }
      for(let y=12;y<104;y+=30) {
        poly([[221,y,z+15],[221,y+22,z+15],[221,y+22,z+49],[221,y,z+49]],color.glassSide);
        poly([[221.1,y+2,z+18],[221.1,y+9,z+18],[221.1,y+9,z+47],[221.1,y+2,z+47]],dark?'#34545b':'#688a8c');
      }
      box(-3,-3,z+58,226,126,4,color.edge,color.side,color.top);
      frontText(String(index+1).padStart(2,'0'),7,122,z+31,13,selected?color.accent:color.ink);
      if(selected) { poly(front,null,color.accent,1.5);poly(side,null,color.accent,1.5); }
      if(room.id) {
        city.faces.push({id:room.id,points:front.map(a=>p(...a))},{id:room.id,points:side.map(a=>p(...a))});
      }
      g.globalAlpha=1;
    });
    const roof=56+levels.length*62;
    box(-6,-6,roof,232,132,9,color.wall,color.side,color.top);
    flat(8,8,200,99,roof+9,color.side);
    box(10,10,roof+9,69,50,24,color.wall,color.side,color.top);
    box(18,18,roof+33,45,30,3,color.metal,color.metal,color.side);
    for(let i=0;i<6;i++) line([21+i*7,20,roof+36.1],[21+i*7,45,roof+36.1],color.edge,.7);
    box(139,15,roof+9,52,32,12,color.metal,color.metal,dark?'#537675':'#8ba5a0');
    for(let i=0;i<4;i++) line([143+i*12,17,roof+21.1],[143+i*12,45,roof+21.1],color.edge,.8);
    // A restrained turquoise sign anchors the identity on the entrance fascia.
    poly([[69,121.8,48],[153,121.8,48],[153,121.8,59],[69,121.8,59]],color.metal);
    frontText(tr("А Р Т Е Л Ь", "A R T E L"),75,122,50,8,dark?'#91e1ce':'#cbf3e0');
    origin=[0,0];zScale=1;
  });
  }
  const actors=cityActors(buildings,city.time);
  for(const car of actors.cars) {
    const {x,y:lane,reverse}=car, paint=[dark?'#69b4a6':'#327e76',dark?'#c9bfa5':'#eee7d2','#ad7964','#718ea5'][car.variant];
    if(!visible(x,lane,40,20,24))continue;
    add(x+lane+26,()=>{
      shadow(x,lane,37,17,12);
      box(x,lane,4,37,18,10,paint,dark?'#435f64':'#537775',paint);
      box(x+9,lane+1,14,20,16,8,color.glassSide,color.glass,paint);
      for(const dx of [6,29])for(const dy of [0,17])box(x+dx,lane+dy,1,5,2,6,'#26383e','#1e3036','#3b4d51');
      box(x+(reverse?0:35),lane+3,8,2,4,3,dark?'#f7e5a9':'#eee6bf');
    });
  }
  for(const person of actors.people) {
    const {x,y,stride}=person, coat=['#b87559','#638da6','#9b8b64','#568f7d'][person.variant];
    if(!visible(x-3,y-3,10,10,23))continue;
    add(x+y+2,()=>{
      shadow(x-2,y-2,6,5,15);
      box(x-2,y-1+stride,0,2,3,7,'#35474b');box(x+2,y-1-stride,0,2,3,7,'#35474b');
      box(x-3,y-2,7,8,5,10,coat,coat,dark?'#c3b79b':'#cbb99e');
      box(x-1,y-1,17,5,4,5,'#d0ad8b','#a48e77','#655e50');
    });
  }
  objects.sort((a,b)=>a.depth-b.depth).forEach(o=>o.draw());
  if(city.selected && w>840) {
    const address=cityAddress(city.rooms.find(r=>r.id===city.selected));
    const building=buildings.find(b=>b.number===address.building);
    const anchor=p(building.x+221,building.y+120,(56+(address.floor-1)*62+33)*CITY_HEIGHT);
    const panel=$('cityPreview'), panelRect=panel.getBoundingClientRect(), canvasRect=canvas.getBoundingClientRect();
    const left=panelRect.left-canvasRect.left, top=panelRect.top-canvasRect.top;
    const end=[left,Math.max(top+38,Math.min(top+panel.clientHeight-38,anchor[1]))];
    if(anchor[0]>=0 && anchor[0]<left-16 && anchor[1]>=0 && anchor[1]<=h) {
    g.beginPath();g.moveTo(...anchor);g.lineTo(anchor[0]+24,anchor[1]);g.lineTo(end[0]-16,end[1]);g.lineTo(...end);
    g.strokeStyle=color.accent;g.lineWidth=1.4;g.stroke();
    g.beginPath();g.arc(...anchor,3.5,0,Math.PI*2);g.fillStyle=color.accent;g.fill();
    }
  }
  // The scene softly recedes at its edges, while the central facade remains crisp.
  const fade=g.createLinearGradient(0,0,0,h);
  fade.addColorStop(0,dark?'#17282ff0':'#e0eaebee');fade.addColorStop(.22,dark?'#17282f00':'#e0eaeb00');
  fade.addColorStop(.88,dark?'#17282f00':'#e0eaeb00');fade.addColorStop(1,dark?'#17282fbb':'#e0eaebaa');
  g.fillStyle=fade;g.fillRect(0,0,w,h);
  // Labels live above the entire scene, with a constant readable CSS font.
  renderCityLabels(c,city.buildings.length?buildings:[]);
  for(const label of city.labels) {
    const end=[Math.max(label.x+8,Math.min(label.x+label.w-8,label.anchor[0])),label.y];
    g.beginPath();g.moveTo(...label.anchor);g.lineTo(...end);
    g.strokeStyle=color.accent;g.globalAlpha=.65;g.lineWidth=1;g.stroke();g.globalAlpha=1;
    g.beginPath();g.arc(...label.anchor,2.5,0,Math.PI*2);g.fillStyle=color.accent;g.fill();
  }
}
function cityResize() {
  const rect=city.canvas.getBoundingClientRect();
  if(!rect.width || !rect.height) return;
  city.cancelGesture?.();
  city.width=rect.width;city.height=rect.height;city.dpr=Math.min(window.devicePixelRatio||1,2);
  city.canvas.width=Math.round(rect.width*city.dpr);city.canvas.height=Math.round(rect.height*city.dpr);
  city.view=cityClampView(cityBaseCamera(),city.view);
  cityUpdateZoomControls();
  city.dirty=true;
}
new ResizeObserver(cityResize).observe(city.canvas);
if(typeof IntersectionObserver!=='undefined') new IntersectionObserver(entries=>{
  city.visible=entries[0].isIntersecting;city.dirty=true;
}).observe(city.canvas);
function cityFrame(now) {
  requestAnimationFrame(cityFrame);
  const elapsed=city.last?Math.min((now-city.last)/1000,.1):0;city.last=now;
  if(document.hidden || !city.visible || !city.width || $('building').hidden || typeof officeMotionPaused !== 'function') return;
  const paused=officeMotionPaused(), theme=document.documentElement.dataset.theme;
  if(theme!==city.theme) { city.theme=theme;city.dirty=true; }
  const button=$('cityMotion'), label=social.reduced.matches?tr("Движение сокращено", "Reduced motion"):paused?tr("Продолжить сцену", "Resume scene"):tr("Пауза сцены", "Pause scene");
  if(button.textContent!==label) {button.textContent=label;button.setAttribute('aria-pressed',String(paused));button.disabled=social.reduced.matches;city.dirty=true;}
  if(!paused) city.time+=elapsed;
  // No continuous paint when paused; cap the street at 30 fps to leave CPU for daemon logs.
  if(!city.dirty && (paused || now-city.painted<33)) return;
  drawCity();city.painted=now;city.dirty=false;
}
initCityControls();
requestAnimationFrame(cityFrame);
