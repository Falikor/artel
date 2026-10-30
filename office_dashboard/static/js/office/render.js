'use strict';
/* Рендер кадра: размер холста, двери, предметы, цикл анимации, подписи над головами, отладка. */

// ------------------------------------------------------------------ рендер
function resize() {
  const stage = $('stage'), canvas = $('scene');
  const w = stage.clientWidth, h = stage.clientHeight;
  if (!w || !h) return; // Hidden office should not destroy its canvas dimensions.
  office.dpr = Math.min(window.devicePixelRatio || 1, 2);
  const pixelWidth = Math.round(w * office.dpr), pixelHeight = Math.round(h * office.dpr);
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) { canvas.width = pixelWidth; canvas.height = pixelHeight; }
  office.scale = Math.min(w, h) / PLATE;
  office.ox = (w - PLATE * office.scale) / 2; office.oy = (h - PLATE * office.scale) / 2;
}

// The scene changes size when panels wrap, not only when the window resizes.
const sceneResizeObserver = new ResizeObserver(resize);
sceneResizeObserver.observe($('stage'));

// ------------------------------------------------------------------ двери кабинета и переговорки
// 07_DOOR_ANIMATIONS: 8 кадров открытия (800 мс), закрытие — те же кадры назад; держится открытой 1.1 с
function doorActors() {
  const list = [...office.workers.values()].filter((w) => w.visible);
  if (office.cat) list.push(office.cat);
  return list;
}
// Нужна ли дверь актёру: он в проёме или его путь в ближайших точках пересекает линию двери
function wantsDoor(door, a) {
  const [x, y] = a.pos;
  // в самом проёме (между комнатой и линией двери); проход мимо по коридору дверь не открывает
  if (Math.abs(x - door.cx) < 42 && y > door.room[1] - 12 && y < door.depthY + 18) return true;
  const pts = [a.pos, ...(a.path || []).slice(0, 2)];
  for (let i = 0; i + 1 < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1];
    if ((ay - door.depthY) * (by - door.depthY) < 0) {
      const k = (door.depthY - ay) / (by - ay), cx = ax + (bx - ax) * k;
      if (Math.abs(cx - door.cx) < 55 && Math.hypot(cx - x, door.depthY - y) < 150) return true;
    }
  }
  return false;
}
// Шаг через линию двери запрещён, пока она не открыта полностью
function doorBlocks(pos, next) {
  for (const door of office.doors) {
    if (door.p >= 0.999) continue;
    const cross = (pos[1] - door.depthY) * (next[1] - door.depthY) <= 0;
    if (cross && Math.abs(pos[0] - door.cx) < 55 && Math.abs(pos[1] - door.depthY) < 26) return true;
  }
  return false;
}
function updateDoors(dt, t) {
  const actors = doorActors();
  for (const door of office.doors) {
    if (actors.some((a) => wantsDoor(door, a))) door.holdUntil = t + door.hold;
    const target = t < door.holdUntil ? 1 : 0;
    door.p = clamp(door.p + Math.sign(target - door.p) * dt / door.duration, 0, 1);
  }
}
function drawSceneDoor(g, door, fg) {
  const img = fg ? door.fg : door.img;
  if (!img) return;
  g.imageSmoothingEnabled = false;
  if (fg) { g.drawImage(img, door.x, door.y); return; }
  const i = Math.round(door.p * (door.frames - 1));
  g.drawImage(img, i * door.fw, 0, door.fw, door.fh, door.x, door.y, door.fw, door.fh);
}

function drawDoor(g) {
  const sheet = office.props, anim = sheet && sheet.anims['office-doors'];
  if (!anim || office.door <= 0) return;
  const fr = anim.frames[Math.round(office.door * (anim.frames.length - 1))];
  const [sx, sy, sw, sh] = DOOR.src, [dx, dy, dw, dh] = DOOR.box;
  g.imageSmoothingEnabled = true;
  g.drawImage(sheet.img, fr.sx + sx, fr.sy + sy, sw, sh, dx, dy, dw, dh);
}

function drawProp(g, key, t) {
  const p = PROPS[key], sheet = office.props;
  if (!sheet || !sheet.anims[p.anim]) return;
  const anim = sheet.anims[p.anim];
  let fr;
  if (key === 'tv') {
    const ms = (t - office.tvStart) * 1000;
    fr = ms < anim.total + 4000 ? frameAt(anim, ms, false) : (t % 30 < 0.05 ? anim.frames[0] : null);
    if (!fr) fr = frameAt(anim, anim.total, false);
  } else if (key === 'printer') {
    const ms = (t - office.printerStart) * 1000;
    fr = ms < anim.total + 2500 ? frameAt(anim, ms, false) : anim.frames[0];
  } else {
    fr = frameAt(anim, t * 1000 + (p.offset || 0), true);
  }
  const [bx0, by0, bx1, by1] = p.bbox;
  g.imageSmoothingEnabled = true;
  g.drawImage(sheet.img, fr.sx + bx0, fr.sy + by0, bx1 - bx0, by1 - by0, p.at[0], p.at[1], (bx1 - bx0) * p.s, (by1 - by0) * p.s);
}

// Reduced motion keeps the current status visible at its permanent desk without walking.
function settleMotionWorker(w) {
  const d = w.data, key = `${d.stage}:${d.issue || ''}:${d.stage_since || ''}:${d.alive}`;
  if (w.stillKey === key) return;
  w.stillKey = key;
  if (w.plan) w.endPlan(office.t,true);
  w.queue = []; w.trans = null; w.pending = null; w.oneShot = null; w.replies = [];
  w.teleport({stage:d.stage,issue:d.issue,...(d.detail || {}),t:d.stage_since});
  if (d.stage === 'stopped') w.visible = false;
}
let lastFrame = performance.now(), lastCards = 0, lastTags = 0, lastPaint = 0;
function loop(now) {
  socialTick(Date.now());
  if (document.hidden || !buildingView.room || !office.plate || document.body.classList.contains('view-stats')) {
    lastFrame = now; requestAnimationFrame(loop); return;
  }
  const dt = Math.min(0.1, (now - lastFrame) / 1000); lastFrame = now;
  office.t += dt;
  const t = office.t, paused = officeMotionPaused();
  if (paused && now - lastPaint < 250) { requestAnimationFrame(loop); return; }
  lastPaint = now;
  const frameTime = paused ? social.freezeAt : t;
  const canvas = $('scene'), g = canvas.getContext('2d');
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, canvas.width, canvas.height); // The stage background follows the theme, including letterboxing.
  g.setTransform(office.dpr * office.scale, 0, 0, office.dpr * office.scale, office.dpr * office.ox, office.dpr * office.oy);
  g.imageSmoothingEnabled = office.scale * office.dpr < 1;
  g.drawImage(office.plate, 0, 0, PLATE, PLATE);

  if (paused) {
    for (const w of office.workers.values()) settleMotionWorker(w);
  } else {
    for (const w of office.workers.values()) { w.stillKey = null; w.update(dt, t); }
    if (office.cat) office.cat.update(dt, t);
    runTimers(t); updateGame(t); planIdle(t);
  }

  // Подсветка экрана переговорки во время деплоя
  const deploying = [...office.workers.values()].some((w) => w.place && w.place.key === 'meeting');
  if (deploying) {
    g.save(); g.globalCompositeOperation = 'lighter';
    g.fillStyle = `rgba(120, 200, 255, ${paused ? 0.12 : 0.10 + 0.08 * Math.sin(t * 4)})`;
    g.fillRect(...MEET_TV); g.restore();
  }

  // Порядок отрисовки по линии ног
  const drawables = [...office.workers.values()].map((w) => ({ y: w.pos[1], draw: () => w.draw(g, frameTime) }));
  if (office.cat) drawables.push({ y: office.cat.pos[1] + 0.5, draw: () => office.cat.draw(g, frameTime) });
  // Двери открываются, когда кто-то входит или выходит
  const nearDoor = [...office.workers.values()].some((w) => w.visible && Math.abs(w.pos[0] - DOOR.zone[0]) < 70 &&
    Math.abs(w.pos[1] - DOOR.zone[1]) < 110);
  if (!paused) office.door = clamp(office.door + (nearDoor ? dt : -dt) / 0.45, 0, 1);
  if (!office.doors.some((d) => d.id === 'office_entrance')) drawables.push({ y: DOOR.box[1] + DOOR.box[3], draw: () => drawDoor(g) });
  if (cabinet.img) drawables.push({ y: cabinet.base, draw: () => drawCabinet(g, frameTime) });
  // Створка сортируется по depthY с актёрами; косяки (foreground) — поверх тех, кто в проёме
  if (!paused) updateDoors(dt, t);
  for (const door of office.doors) {
    drawables.push({ y: door.depthY, draw: () => drawSceneDoor(g, door, false) });
    drawables.push({ y: door.depthY + 0.6, draw: () => drawSceneDoor(g, door, true) });
  }
  for (const d of DECOR) {
    const img = office.decor[d.key];
    if (img) drawables.push({ y: d.base, draw: () => { g.imageSmoothingEnabled = false; g.drawImage(img, d.at[0], d.at[1]); } });
  }
  for (const key of Object.keys(PROPS)) {
    const p = PROPS[key];
    drawables.push({ y: p.at[1] + (p.bbox[3] - p.bbox[1]) * p.s, draw: () => drawProp(g, key, frameTime) });
  }
  drawables.sort((a, b) => a.y - b.y).forEach((d) => d.draw());

  if (DEBUG) drawDebug(g);
  // Labels contain DOM measurements: avoid reflow on every animation frame.
  if (now - lastTags > 100 || paused) {
    lastTags = now;
    for (const w of office.workers.values()) w.updateTag(t);
    layoutTags();
    if (office.cat) office.cat.updateTag(t);
  }
  if (now - lastCards > 1000) { lastCards = now; renderCards(); }
  requestAnimationFrame(loop);
}

// Метки соседей не должны перекрываться: нижние по сцене поднимаем над верхними
function layoutTags() {
  const placed = [];
  const list = [...office.workers.values()].filter((w) => w.visible && w.tagBox).sort((a, b) => b.pos[1] - a.pos[1]);
  for (const w of list) {
    const b = w.tagBox;
    let y = b.sy;
    for (let guard = 0; guard < 8; guard++) {
      const hit = placed.find((p) => Math.abs(p.x - b.sx) < (p.w + b.w) / 2 + 4 && y > p.y - p.h - 2 && y - b.h < p.y + 2);
      if (!hit) break;
      y = hit.y - hit.h - 3;
    }
    y = Math.max(b.h + 4, Math.min($('stage').clientHeight - 4, y));
    const x = Math.max(b.w / 2 + 4, Math.min($('stage').clientWidth - b.w / 2 - 4, b.sx));
    placed.push({ x, y, w: b.w, h: b.h });
    w.tag.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%) scale(${b.k})`;
  }
}

function drawDebug(g) {
  g.save();
  g.strokeStyle = 'rgba(255,0,255,.7)'; g.lineWidth = 2; g.font = '12px monospace';
  for (const [a, b] of EDGES) { g.beginPath(); g.moveTo(...N[a]); g.lineTo(...N[b]); g.stroke(); }
  g.fillStyle = '#ff0'; for (const [k, [x, y]] of Object.entries(N)) { g.fillRect(x - 3, y - 3, 6, 6); g.fillText(k, x + 5, y - 5); }
  g.fillStyle = '#0ff'; SEATS.forEach((s) => { g.fillRect(s.pos[0] - 3, s.pos[1] - 3, 6, 6); g.fillText(s.key, s.pos[0] + 5, s.pos[1] + 12); });
  g.fillStyle = '#f80'; [...LOUNGE.map((l) => l.pos), ...MEET, ...BOARD, ...PRINTER].forEach(([x, y]) => g.fillRect(x - 3, y - 3, 6, 6));
  g.restore();
}
