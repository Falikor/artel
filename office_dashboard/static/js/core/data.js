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
  if (!src) return Promise.reject(new Error(tr("Не указан файл изображения", "No image file specified")));
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(tr("Истекло время загрузки изображения", "Image loading timed out"))), 15000); });
  return Promise.race([loadImage(src), timeout]).finally(() => clearTimeout(timer));
}
function usableCharacter(character) {
  // Every pose can fall back to idle_down. Empty or malformed clips cannot enter the renderer.
  for (const [name, anim] of Object.entries(character.anims || {})) {
    if (!anim.cells?.length || anim.cells.length !== anim.dur?.length ||
        !Number.isFinite(anim.total) || anim.total <= 0 || anim.dur.some(value => !Number.isFinite(value) || value <= 0)) delete character.anims[name];
  }
  if (!character.anims?.idle_down) throw new Error(tr("Нет базовой анимации персонажа", "Missing base character animation"));
  return character;
}
async function boot() {
  // Data, logs, keyboard and controls must never depend on images or sprite manifests.
  buildLegend(); resize(); window.addEventListener('resize', resize);
  setupInput(); connect(); requestAnimationFrame(loop);
  sceneAssetNotice(tr("Загружаем оформление офиса…", "Loading the office artwork…"));
  let assets, timer;
  const controller = new AbortController();
  try {
    timer = setTimeout(() => controller.abort(), 15000);
    const response = await fetch('/api/assets', {signal: controller.signal});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    assets = await response.json();
    if (!assets || typeof assets !== 'object') throw new Error(tr("Некорректный список ассетов", "Invalid asset list"));
  } catch (error) {
    console.warn(tr("Оформление офиса недоступно", "Office artwork is unavailable"), error);
    sceneAssetNotice(tr("Не удалось загрузить оформление офиса. Статусы, логи и управление доступны. Обновите страницу, чтобы повторить загрузку.", "Could not load the office artwork. Status, logs and controls are available. Reload the page to try again."), true);
    return;
  } finally { clearTimeout(timer); }
  const failures = new Set();
  if (assets.error) failures.add(tr("оформление офиса", "office artwork"));
  const part = async (label, load) => {
    try { await load(); }
    catch (error) { failures.add(label); console.warn(tr("Не удалось загрузить: ", "Could not load: ") + label, error); }
  };
  const jobs = [part(tr("фон офиса", "office background"), async () => { office.plate = await sceneImage(assets.plate); })];
  for (const door of Array.isArray(assets.doors) ? assets.doors : []) jobs.push(part(tr("двери", "doors"), async () => {
    const img = await sceneImage(door.atlas);
    let foreground = null;
    if (door.foreground) await part(tr("оформление дверей", "door artwork"), async () => { foreground = await sceneImage(door.foreground); });
    const open = door.animations.open || {durationsMs: [800]};
    office.doors.push({id:door.id, img, fg:foreground, fw:door.frameSize.w, fh:door.frameSize.h,
      x:door.scenePosition.x, y:door.scenePosition.y, depthY:door.depthY, cx:door.waypoints.corridor.x,
      room:[door.waypoints.room.x,door.waypoints.room.y], corridor:[door.waypoints.corridor.x,door.waypoints.corridor.y],
      frames:img.width / door.frameSize.w, duration:open.durationsMs.reduce((sum,value) => sum+value,0) / 1000,
      hold:(door.autoCloseDelayMs || 1100) / 1000, p:0, holdUntil:0});
  }));
  if (assets.office) jobs.push(part(tr("предметы офиса", "office objects"), async () => {
    const sheet = buildSheet(await sceneImage(assets.office.atlas), assets.office.manifest);
    for (const [key, anim] of Object.entries(sheet.anims)) if (!anim.frames?.length || !Number.isFinite(anim.total) || anim.total <= 0) delete sheet.anims[key];
    office.props = sheet;
  }));
  const lounge = assets.lounge;
  if (lounge?.cabinet) jobs.push(part(tr("зона отдыха", "lounge"), async () => {
    const item = lounge.cabinet, image = await sceneImage(item.atlas);
    const pos = [item.scenePosition.x,item.scenePosition.y], ip = [item.interactionPoint.x,item.interactionPoint.y];
    const base = item.collisionFootprint ? item.collisionFootprint.y+item.collisionFootprint.height : 800;
    Object.assign(cabinet, {img:image,frames:item.frames,pos,ip,base});
  }));
  if (assets.cat) jobs.push(part(tr("персонаж кошки", "cat character"), async () => {
    office.cat = new Cat(buildCat(assets.cat.manifest,await sceneImage(assets.cat.atlas))); $('memo').hidden = false;
  }));
  for (const [key,src] of Object.entries(assets.decor || {})) jobs.push(part(tr("декор", "decor"), async () => { office.decor[key] = await sceneImage(src); }));
  const characters = Array.isArray(assets.characters) ? assets.characters : [];
  if (!characters.length) failures.add(tr("персонажи", "characters"));
  for (const definition of characters) jobs.push(part(tr("персонажи", "characters"), async () => {
    const character = usableCharacter(buildCharacter(definition,await sceneImage(definition.atlas)));
    // A bad thumbnail cannot remove an otherwise usable animated character.
    office.chars[definition.id] = character;
    await part(tr("миниатюры персонажей", "character thumbnails"), async () => { office.thumbs[character.id] = charThumb(character); });
    const extra = lounge?.characters?.[definition.id];
    if (extra) await part(tr("дополнительные анимации", "additional animations"), async () => {
      const extended = {...character, anims:{...character.anims}};
      addLoungeAnims(extended,extra,await sceneImage(extra.atlas),lounge.pivot || {x:80,y:136});
      office.chars[definition.id] = usableCharacter(extended);
    });
  }));
  await Promise.allSettled(jobs);
  if (!Object.keys(office.chars).length) failures.add(tr("персонажи", "characters"));
  // SSE may have delivered the complete roster before even the first image loaded.
  syncOffice(); renderBuilding(); renderCards();
  if (drawer.id) refreshDrawer(false);
  if (failures.size) {
    sceneAssetNotice(tr("Часть оформления недоступна: ", "Some artwork is unavailable: ") + [...failures].join(', ') + tr(". Статусы, логи и управление работают. Обновите страницу, чтобы повторить загрузку.", ". Status, logs and controls are working. Reload the page to try again."), true);
  } else sceneAssetNotice('');
}

// ------------------------------------------------------------------ данные
function connect() {
  const conn = $('conn');
  const setConn = (cls, text) => { conn.className = 'conn ' + cls; conn.querySelector('span').textContent = text; };
  let es;
  const open = () => {
    es = new EventSource('/api/stream');
    es.onopen = () => setConn('ok', tr("онлайн", "online"));
    es.onmessage = (m) => { try { apply(JSON.parse(m.data)); } catch (e) { console.error(e); } };
    es.onerror = () => { setConn('bad', tr("нет связи — переподключение", "offline — reconnecting")); };
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
