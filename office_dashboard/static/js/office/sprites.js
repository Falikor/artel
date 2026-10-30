'use strict';
/* Спрайты: нарезка атласов, анимации персонажей, общий объект сцены office. */

// ------------------------------------------------------------------ спрайты
// Каждая строка атласа нормализуется по bbox: одинаковый рост и линия ног
function buildSheet(img, manifest, opts = {}) {
  const { width: cw, height: ch } = manifest.cell;
  const canvas = document.createElement('canvas');
  canvas.width = img.width; canvas.height = img.height;
  const g = canvas.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, 0);
  const px = g.getImageData(0, 0, img.width, img.height).data;
  const anims = {};
  for (const a of manifest.animations) {
    const id = a.id.replace(/^office-character-/, '');
    const frames = [];
    for (let f = 0; f < a.frames; f++) {
      const sx = f * cw, sy = a.row * ch;
      let x0 = cw, y0 = ch, x1 = -1, y1 = -1;
      for (let y = 0; y < ch; y += 2) {
        const rowOff = ((sy + y) * img.width + sx) * 4 + 3;
        for (let x = 0; x < cw; x += 2) {
          if (px[rowOff + x * 4] > 24) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
        }
      }
      frames.push({ sx, sy, empty: x1 < 0, bbox: [x0, y0, x1 + 2, y1 + 2] });
    }
    const ok = frames.filter((f) => !f.empty);
    const h = median(ok.map((f) => f.bbox[3] - f.bbox[1])) || ch;
    anims[id] = {
      id, frames, loop: a.playback === 'loop',
      dur: (a.durationsMs || []).map((d) => Math.max(33, d)),
      feet: Math.max(...ok.map((f) => f.bbox[3]), 1),
      cx: median(ok.map((f) => (f.bbox[0] + f.bbox[2]) / 2)) || cw / 2,
      scale: opts.height ? opts.height / h : 1,
    };
    const total = anims[id].dur.reduce((s, d) => s + d, 0);
    if (!total) anims[id].dur = frames.map(() => manifest.frameDurationMs || 100);
    anims[id].total = anims[id].dur.reduce((s, d) => s + d, 0);
  }
  return { img, cw, ch, anims };
}
function frameAt(anim, ms, loop) {
  let t = loop ? ms % anim.total : Math.min(ms, anim.total - 1);
  for (let i = 0; i < anim.frames.length; i++) {
    t -= anim.dur[i];
    if (t < 0) return anim.frames[i].empty ? anim.frames[Math.max(0, i - 1)] : anim.frames[i];
  }
  return anim.frames[anim.frames.length - 1];
}

const filterSupported = (() => {
  try { const c = document.createElement('canvas').getContext('2d'); c.filter = 'grayscale(1)'; return c.filter === 'grayscale(1)'; } catch { return false; }
})();

// ------------------------------------------------------------------ сцена
const office = {
  plate: null, props: null, chars: {}, thumbs: {}, workers: new Map(), selected: null,
  tvStart: -1e9, printerStart: -1e9, t: 0,
  scale: 1, ox: 0, oy: 0, dpr: 1,
  reserved: new Map(), // ключ места в лаунже → id демона
  spots: new Set(),     // занятые точки для разговоров, кулер, окна
  doors: [],            // двери кабинета руководителя и переговорки
  decor: {},            // картинки кухонного уголка
  door: 0,              // насколько открыты входные двери, 0..1
  nextPlan: 0,
};

// Исправления брака в атласах v3: анимация берётся зеркалом парной
const ANIM_FIXES = {
  // в lounge_left хвостик остаётся справа при повороте головы, крайние кадры смотрят вправо
  worker_orange_yellow: { lounge_left: { mirrorOf: 'lounge_right' } },
};

function makeAnim(cells, dur, loop) {
  return { cells, n: cells.length, dur, total: dur.reduce((s, d) => s + d, 0) || 1, loop };
}

// Ширина следа ног в кадре (строки 100..113 ячейки): по ней ищем «шаг» и «ноги вместе»
function feetWidths(img, row, fw, fh, cols) {
  const c = document.createElement('canvas'); c.width = fw * cols; c.height = 14;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(img, 0, row * fh + 100, fw * cols, 14, 0, 0, fw * cols, 14);
  const px = g.getImageData(0, 0, fw * cols, 14).data, out = [];
  for (let f = 0; f < cols; f++) {
    let x0 = fw, x1 = -1;
    for (let y = 0; y < 14; y++) for (let x = 0; x < fw; x++) {
      if (px[(y * fw * cols + f * fw + x) * 4 + 3] > 24) { if (x < x0) x0 = x; if (x > x1) x1 = x; }
    }
    out.push(x1 < 0 ? 0 : x1 - x0);
  }
  return out;
}

// В атласе v3 у ходьбы вбок ноги почти во всех кадрах расставлены одинаково — шаг не читается.
// Собираем 4-фазный цикл: широкий шаг → ноги вместе (кадр idle) → другой шаг → ноги вместе.
function sideWalk(img, def, anims, dir) {
  const walk = def.animations[`walk_${dir}`], idle = def.animations[`idle_${dir}`];
  if (!walk || !idle) return null;
  const { w: fw, h: fh } = def.frameSize;
  const ww = feetWidths(img, walk.row, fw, fh, walk.durationsMs.length);
  const iw = feetWidths(img, idle.row, fw, fh, 1)[0];
  if (Math.min(...ww) <= iw + 4) return null; // в цикле уже есть фаза «ноги вместе» — оставляем как есть
  const n = ww.length;
  const a = ww.indexOf(Math.max(...ww));
  let b = (a + 4) % n;
  for (const d of [4, 3, 5]) { const k = (a + d) % n; if (ww[k] > ww[b]) b = k; }
  const pass = { row: idle.row, col: 0, dy: -1 };
  return makeAnim([{ row: walk.row, col: a }, pass, { row: walk.row, col: b }, pass], [150, 110, 150, 110], true);
}

// Персонаж v3: atlas 8 столбцов × N строк, у всех кадров общая точка ног (pivot)
function buildCharacter(def, img) {
  const anims = {};
  for (const [name, a] of Object.entries(def.animations)) {
    const dur = (a.durationsMs || []).map((d) => Math.max(33, d));
    anims[name] = makeAnim(dur.map((_, col) => ({ row: a.row, col })), dur, !!a.loop);
  }
  for (const dir of ['left', 'right']) {
    const w = sideWalk(img, def, anims, dir);
    if (w) anims[`walk_${dir}`] = w;
  }
  for (const [name, fix] of Object.entries(ANIM_FIXES[def.id] || {})) {
    const src = anims[fix.mirrorOf];
    if (src) anims[name] = makeAnim(src.cells.map((c) => ({ ...c, flip: true })), src.dur, src.loop);
  }
  return { id: def.id, img, fw: def.frameSize.w, fh: def.frameSize.h, px: def.pivot.x, py: def.pivot.y, anims };
}

// Набор 08 (диван, кресло, жесты, приставка): кадры 160×160, точка ног (80,136). Левые клипы — зеркало правых
// (flipX), frameOverrides подменяют отдельные кадры (например, standing_left без зеркала)
function addLoungeAnims(ch, def, img, pivot) {
  for (const [name, a] of Object.entries(def.animations)) {
    const cells = a.frames.map((frameName, i) => {
      const o = (a.frameOverrides || {})[String(i)];
      const fname = o ? o.frame : frameName, rect = def.frames[fname];
      if (!rect) return null;
      return { sx: rect[0], sy: rect[1], sw: rect[2], sh: rect[3], flip: o ? !!o.flipX : !!a.flipX };
    });
    if (cells.some((c) => !c)) continue;
    const dur = (a.durationsMs || []).map((d) => Math.max(33, d));
    const anim = makeAnim(cells, dur, !!a.loop);
    anim.img = img; anim.px = pivot.x; anim.py = pivot.y; anim.events = a.events || [];
    ch.anims[name] = anim;
  }
}
function frameIndex(anim, ms, loop) {
  let t = loop ? ((ms % anim.total) + anim.total) % anim.total : clamp(ms, 0, anim.total - 1);
  for (let i = 0; i < anim.n; i++) { t -= anim.dur[i]; if (t < 0) return i; }
  return anim.n - 1;
}
