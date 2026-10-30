'use strict';
/* Загрузка ассетов и данные: boot, поток SSE, места демонов, применение снимка состояния. */

// ------------------------------------------------------------------ загрузка
function sceneAssetNotice(message, global = false) {
  const notice = $('notice');
  notice.textContent = message; notice.hidden = !message;
  let status = $('sceneAssetStatus');
  if (!status) {
    status = document.createElement('p'); status.id = 'sceneAssetStatus';
    status.className = 'asset-status'; status.setAttribute('role', 'status');
    $('building').before(status);
  }
  status.textContent = global ? message : ''; status.hidden = !global || !message;
}
function sceneImage(src) {
  if (!src) return Promise.reject(new Error('Не указан файл изображения'));
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Истекло время загрузки изображения')), 15000); });
  return Promise.race([loadImage(src), timeout]).finally(() => clearTimeout(timer));
}
function usableCharacter(character) {
  // Every pose can fall back to idle_down. Empty or malformed clips cannot enter the renderer.
  for (const [name, anim] of Object.entries(character.anims || {})) {
    if (!anim.cells?.length || anim.cells.length !== anim.dur?.length ||
        !Number.isFinite(anim.total) || anim.total <= 0 || anim.dur.some(value => !Number.isFinite(value) || value <= 0)) delete character.anims[name];
  }
  if (!character.anims?.idle_down) throw new Error('Нет базовой анимации персонажа');
  return character;
}
async function boot() {
  // Data, logs, keyboard and controls must never depend on images or sprite manifests.
  buildLegend(); resize(); window.addEventListener('resize', resize);
  setupInput(); connect(); requestAnimationFrame(loop);
  sceneAssetNotice('Загружаем оформление офиса…');
  let assets, timer;
  const controller = new AbortController();
  try {
    timer = setTimeout(() => controller.abort(), 15000);
    const response = await fetch('/api/assets', {signal: controller.signal});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    assets = await response.json();
    if (!assets || typeof assets !== 'object') throw new Error('Некорректный список ассетов');
  } catch (error) {
    console.warn('Оформление офиса недоступно', error);
    sceneAssetNotice('Не удалось загрузить оформление офиса. Статусы, логи и управление доступны. Обновите страницу, чтобы повторить загрузку.', true);
    return;
  } finally { clearTimeout(timer); }
  const failures = new Set();
  if (assets.error) failures.add('оформление офиса');
  const part = async (label, load) => {
    try { await load(); }
    catch (error) { failures.add(label); console.warn('Не удалось загрузить: ' + label, error); }
  };
  const jobs = [part('фон офиса', async () => { office.plate = await sceneImage(assets.plate); })];
  for (const door of Array.isArray(assets.doors) ? assets.doors : []) jobs.push(part('двери', async () => {
    const img = await sceneImage(door.atlas);
    let foreground = null;
    if (door.foreground) await part('оформление дверей', async () => { foreground = await sceneImage(door.foreground); });
    const open = door.animations.open || {durationsMs: [800]};
    office.doors.push({id:door.id, img, fg:foreground, fw:door.frameSize.w, fh:door.frameSize.h,
      x:door.scenePosition.x, y:door.scenePosition.y, depthY:door.depthY, cx:door.waypoints.corridor.x,
      room:[door.waypoints.room.x,door.waypoints.room.y], corridor:[door.waypoints.corridor.x,door.waypoints.corridor.y],
      frames:img.width / door.frameSize.w, duration:open.durationsMs.reduce((sum,value) => sum+value,0) / 1000,
      hold:(door.autoCloseDelayMs || 1100) / 1000, p:0, holdUntil:0});
  }));
  if (assets.office) jobs.push(part('предметы офиса', async () => {
    const sheet = buildSheet(await sceneImage(assets.office.atlas), assets.office.manifest);
    for (const [key, anim] of Object.entries(sheet.anims)) if (!anim.frames?.length || !Number.isFinite(anim.total) || anim.total <= 0) delete sheet.anims[key];
    office.props = sheet;
  }));
  const lounge = assets.lounge;
  if (lounge?.cabinet) jobs.push(part('зона отдыха', async () => {
    const item = lounge.cabinet, image = await sceneImage(item.atlas);
    const pos = [item.scenePosition.x,item.scenePosition.y], ip = [item.interactionPoint.x,item.interactionPoint.y];
    const base = item.collisionFootprint ? item.collisionFootprint.y+item.collisionFootprint.height : 800;
    Object.assign(cabinet, {img:image,frames:item.frames,pos,ip,base});
  }));
  if (assets.cat) jobs.push(part('персонаж кошки', async () => {
    office.cat = new Cat(buildCat(assets.cat.manifest,await sceneImage(assets.cat.atlas))); $('memo').hidden = false;
  }));
  for (const [key,src] of Object.entries(assets.decor || {})) jobs.push(part('декор', async () => { office.decor[key] = await sceneImage(src); }));
  const characters = Array.isArray(assets.characters) ? assets.characters : [];
  if (!characters.length) failures.add('персонажи');
  for (const definition of characters) jobs.push(part('персонажи', async () => {
    const character = usableCharacter(buildCharacter(definition,await sceneImage(definition.atlas)));
    // A bad thumbnail cannot remove an otherwise usable animated character.
    office.chars[definition.id] = character;
    await part('миниатюры персонажей', async () => { office.thumbs[character.id] = charThumb(character); });
    const extra = lounge?.characters?.[definition.id];
    if (extra) await part('дополнительные анимации', async () => {
      const extended = {...character, anims:{...character.anims}};
      addLoungeAnims(extended,extra,await sceneImage(extra.atlas),lounge.pivot || {x:80,y:136});
      office.chars[definition.id] = usableCharacter(extended);
    });
  }));
  await Promise.allSettled(jobs);
  if (!Object.keys(office.chars).length) failures.add('персонажи');
  // SSE may have delivered the complete roster before even the first image loaded.
  syncOffice(); renderBuilding(); renderCards();
  if (drawer.id) refreshDrawer(false);
  if (failures.size) {
    sceneAssetNotice('Часть оформления недоступна: ' + [...failures].join(', ') + '. Статусы, логи и управление работают. Обновите страницу, чтобы повторить загрузку.', true);
  } else sceneAssetNotice('');
}

// ------------------------------------------------------------------ данные
function connect() {
  const conn = $('conn');
  const setConn = (cls, text) => { conn.className = 'conn ' + cls; conn.querySelector('span').textContent = text; };
  let es;
  const open = () => {
    es = new EventSource('/api/stream');
    es.onopen = () => setConn('ok', 'онлайн');
    es.onmessage = (m) => { try { apply(JSON.parse(m.data)); } catch (e) { console.error(e); } };
    es.onerror = () => { setConn('bad', 'нет связи — переподключение'); };
  };
  open();
}

let lastSnapshot = { daemons: [] };
function apply(snap) {
  if (snap.now) clockSkew = snap.now - Date.now() / 1000;
  const officesChanged = JSON.stringify(lastSnapshot.office_memberships) !== JSON.stringify(snap.office_memberships);
  lastSnapshot = snap;
  if (typeof syncPromptStatus === 'function') syncPromptStatus(snap);
  $('demoBadge').hidden = !snap.demo;
  renderBuilding();
  syncOffice();
  renderCards();
  if (drawer.pickChar) renderCharPicker();
  if (officesChanged && !$('stats').hidden) { quality.key = null; renderStats(); }
}
