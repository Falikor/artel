'use strict';
/* Выбор персонажа демона в панели (👤): миниатюры, кто кем занят, сохранение. */

// ------------------------------------------------------------------ персонаж демона
// Кто главнее: выбор в панели демона → general.character в конфиге → автоматика (сервер назначает
// свободного персонажа один раз и запоминает). Здесь — только запасной вариант до ответа сервера.
const CHAR_LABELS = {
  worker_orange_yellow: 'Рыжая, в жёлтом', worker_dark_purple: 'Тёмные волосы, в фиолетовом',
  worker_brown_green: 'Каштановые, в зелёном', worker_brown_red: 'Каштановые, в красном',
  worker_black_charcoal: 'Чёрные, в графитовом', worker_blond_blue: 'Светлые, в синем', manager_navy: 'Руководитель в тёмно-синем',
};
function charFor(d, slot) {
  const ids = Object.keys(office.chars);
  return office.chars[d.character] || office.chars[CHAR_ORDER[slot % CHAR_ORDER.length]] || office.chars[ids[slot % ids.length]];
}
// Миниатюра: первый кадр «стоит лицом к нам», обрезанный по фигуре
function charThumb(ch) {
  const a = ch.anims.idle_down || Object.values(ch.anims)[0];
  const cell = a.cells[0], c = document.createElement('canvas');
  const sx = (cell.col || 0) * ch.fw + 28, sy = (cell.row || 0) * ch.fh + 12, sw = 72, sh = 104;
  c.width = sw; c.height = sh;
  const g = c.getContext('2d');
  g.imageSmoothingEnabled = false;
  g.drawImage(ch.img, sx, sy, sw, sh, 0, 0, sw, sh);
  return c.toDataURL();
}
function charOrder() {
  return [...CHAR_ORDER.filter((id) => office.chars[id]), ...Object.keys(office.chars).filter((id) => !CHAR_ORDER.includes(id))];
}
function renderCharPicker() {
  const box=$('drawerChars'),d=lastSnapshot.daemons.find(x=>x.id===drawer.id);
  if(!d||!drawer.pickChar){box.hidden=true;return;}
  const users={};for(const other of lastSnapshot.daemons)if(other.id!==d.id&&other.character)(users[other.character] ||= []).push(displayName(other));
  const source={dashboard:'Выбран в дашборде',config:'Из настроек демона',auto:'Назначен автоматически'}[d.character_source]||'';
  const disabled=lastSnapshot.control===false?' disabled':'';
  const html=`<div class="char-head"><h3>Внешность</h3><p>${esc(source)}${d.character_warning?' · '+esc(d.character_warning):''}</p>${d.character_source==='dashboard'?'<button class="btn" data-char=""'+disabled+'>Вернуть персонажа из настроек</button>':''}</div>
    <div class="char-list" role="group" aria-label="Персонаж">${charOrder().map(id=>`<button type="button" class="char-opt${d.character===id?' on':''}" data-char="${esc(id)}" aria-pressed="${d.character===id}"${disabled}><img src="${office.thumbs[id]||''}" alt=""><span>${esc(CHAR_LABELS[id]||id)}</span>${users[id]?`<small>Ещё у ${users[id].length} ${users[id].length===1?'демона':'демонов'}</small>`:''}</button>`).join('')}</div>
    <h4>Цвет одежды</h4><div class="appearance-pick" role="group" aria-label="Цвет одежды">${LOOKS.map((label,variant)=>`<button type="button" data-variant="${variant}" class="${d.appearance===variant?'on':''}" aria-pressed="${d.appearance===variant}"${disabled}><img src="${appearanceThumb({...d,appearance:variant})}" alt="">${esc(label)}</button>`).join('')}</div>`;
  drawerMarkup(box,html);box.hidden=false;
}
async function chooseCharacter(id,character) {
  if(drawer.characterSaving)return;drawer.characterSaving=true;
  const buttons=[...$('drawerChars').querySelectorAll('button')];buttons.forEach(button=>button.disabled=true);
  try {
    const response=await fetch('/api/characters',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,character:character||null})});
    const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'Не удалось сохранить персонажа.');
    const daemon=lastSnapshot.daemons.find(x=>x.id===id),worker=office.workers.get(id);
    if(character&&daemon){daemon.character=character;daemon.character_source='dashboard';}
    if(character&&worker&&office.chars[character]){worker.char=office.chars[character];worker.sayLine('Новый образ!',office.t,2.2);}
    if(drawer.id===id){drawerNotice('Персонаж сохранён.');renderCharPicker();refreshDrawer(false);}
  }catch(error){if(drawer.id===id)drawerNotice(error.message,true);}
  finally{drawer.characterSaving=false;buttons.forEach(button=>button.disabled=lastSnapshot.control===false);}
}
