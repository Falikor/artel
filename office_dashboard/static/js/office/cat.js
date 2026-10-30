'use strict';
/* Кокошка (только с флагом --cat): спрайт, маршруты, сон и реакции на людей. */

// ------------------------------------------------------------------ Кокошка
// Кошка Кокошка всегда живёт в офисе: гуляет, сидит, спит на диване, заходит к демонам.
const CAT_NAME = 'Кокошка';
const CAT_SPEED = 46;  // px/с — неспешная кошачья походка
// Строки атласа нарисованы в разном масштабе: сидящая кошка в ячейке крупнее идущей, прыжок — мельче.
// Приводим каждую строку к пропорциям рядом с демонами (рост человека ~100 px):
// сидит ~44 px, длина с хвостом на ходу ~58 px, свернувшись во сне ~50 px.
const CAT_ROWS = {
  idle:            { fit: 'h', size: 44 },
  jump:            { fit: 'h0', size: 44 },
  'walk-left':     { fit: 'w', size: 58, perFrame: true },
  'walk-right':    { fit: 'w', size: 58, perFrame: true },
  'walk-forward':  { fit: 'w', size: 23, perFrame: true },
  'walk-backward': { fit: 'w', size: 22, perFrame: true, clipTop: 50 }, // в двух кадрах над головой лишние пиксели
  sleep:           { fit: 'w', size: 50 },
};
// Куда гулять: пол у столов, проходы, кухня (выпрашивает еду), переговорка, кабинет менеджера
const CAT_SPOTS = [
  { pos: [660, 915] }, { pos: [930, 690] }, { pos: [300, 640] }, { pos: [130, 690] }, { pos: [520, 800] },
  { pos: [760, 600] }, { pos: [1040, 700] }, { pos: [620, 960] }, { pos: [470, 880], node: 'pr_s' },
  { pos: [520, 400], node: 'mgr_door', say: 'мяу? (еда?)' }, { pos: [330, 300], node: 'mgr_in' },
  { pos: [720, 330], node: 'meet_w' }, { pos: [1070, 420], node: 'meet_e' }, { pos: [960, 955] },
];
// Где спать: ковёр в лаунже, ковёр у менеджера, диван (запрыгивает), угол переговорки
const CAT_BEDS = [
  { pos: [930, 935], node: 'lb_m' }, { pos: [330, 300], node: 'mgr_in' }, { pos: [720, 420], node: 'meet_w' },
  { pos: [1036, 878], node: 'sofa_l', from: [989, 876], sofa: 'sofa2' },
];
const CAT_LINES = {
  cat: ['мяу', 'мрр', 'мяу?', 'мур-мур', 'мрряу'],
  greet: ['Кокошка!', 'Кис-кис-кис', 'Привет, Кокошка', 'Кто тут у нас пушистый?', 'Кокошка, ты моя хорошая',
    'Опять на клавиатуру хочешь?', 'Кокошка пришла проверить код', 'Ревьюер пришёл :)', 'Иди сюда, поглажу',
    'Кокошка, без тебя не деплоим'],
  sleep: ['Тсс, Кокошка спит', 'Не будем будить', 'Спит крепче прода в выходные', 'Сладко спит…'],
};

function buildCat(manifest, img) {
  const { width: cw, height: ch } = manifest.cell;
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
  const px = g.getImageData(0, 0, img.width, img.height).data;
  const anims = {};
  for (const a of manifest.animations) {
    const name = a.id.replace(/^.*cat-/, '');
    const cfg = CAT_ROWS[name] || { fit: 'h', size: 40 };
    const top = cfg.clipTop || 0;
    const frames = [];
    for (let f = 0; f < a.frames; f++) {
      const sx = f * cw, sy = a.row * ch;
      let x0 = cw, y0 = ch, x1 = -1, y1 = -1;
      for (let y = top; y < ch; y++) {
        const off = ((sy + y) * img.width + sx) * 4 + 3;
        for (let x = 0; x < cw; x++) if (px[off + x * 4] > 24) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      }
      frames.push({ sx, sy, top, bbox: [x0, y0, x1 + 1, y1 + 1] });
    }
    const ok = frames.filter((f) => f.bbox[2] > f.bbox[0]);
    const dim = cfg.fit === 'w' ? median(ok.map((f) => f.bbox[2] - f.bbox[0]))
      : cfg.fit === 'h0' ? ok[0].bbox[3] - ok[0].bbox[1] : median(ok.map((f) => f.bbox[3] - f.bbox[1]));
    const feet = Math.max(...ok.map((f) => f.bbox[3])), cx = median(ok.map((f) => (f.bbox[0] + f.bbox[2]) / 2));
    for (const f of frames) {
      f.ax = cfg.perFrame ? (f.bbox[0] + f.bbox[2]) / 2 : cx;
      f.ay = cfg.perFrame ? f.bbox[3] : feet;
    }
    const dur = a.durationsMs.map((d) => Math.max(33, d));
    anims[name] = { frames, dur, total: dur.reduce((s, d) => s + d, 0), loop: a.playback === 'loop', scale: cfg.size / dim,
      height: (feet - median(ok.map((f) => f.bbox[1]))) * (cfg.size / dim) };
  }
  return { img, cw, ch, anims };
}

class Cat {
  constructor(sheet) {
    this.sheet = sheet;
    const start = CAT_SPOTS[Math.floor(Math.random() * CAT_SPOTS.length)];
    this.pos = [...start.pos]; this.node = start.node || nearestNode(start.pos);
    this.path = []; this.mode = 'sit'; this.dir = 'down'; this.animT0 = 0;
    this.until = office.t + rnd(3, 8); this.nextMeow = office.t + rnd(4, 10); this.nextGlance = 0;
    this.onArrive = null; this.jump = null; this.bed = null; this.speech = null; this.replies = [];
    this.tag = document.createElement('div'); this.tag.className = 'tag cat';
    this.tag.innerHTML = `<div class="bubble"></div><div class="name"><i class="heart">♥</i><span>${CAT_NAME}</span></div>`;
    $('tags').appendChild(this.tag);
  }

  say(text, t, dur = 1.8) { this.speech = { text, until: t + dur }; }
  get resting() { return (this.mode === 'sit' || this.mode === 'sleep') && !this.path.length && !this.jump; }

  goTo(pos, node, t, onArrive) {
    // Маршрут от узла, к которому привязано текущее место (а не ближайшего — тот может быть за стеной)
    this.path = [...route(this.node, node).map((n) => N[n]), pos];
    this.mode = 'walk'; this.onArrive = onArrive; this.targetNode = node;
  }

  startJump(to, t, then) {
    this.mode = 'jump'; this.jump = { from: [...this.pos], to, t0: t, then };
  }

  // Слезть с дивана перед тем, как идти дальше
  leave(t, next) {
    if (this.bed && this.bed.sofa) {
      const bed = this.bed; this.bed = null;
      this.startJump(bed.from, t, (t2) => { office.reserved.delete(bed.sofa); this.mode = 'sit'; next(t2); });
      return;
    }
    this.bed = null;
    next(t);
  }

  decide(t) {
    this.leave(t, (t2) => {
      const r = Math.random();
      if (r < 0.25 && this.visitDemon(t2)) return;
      if (r < 0.58) { this.goSleep(t2); return; }
      const spot = pick(CAT_SPOTS);
      this.goTo(spot.pos, spot.node || nearestNode(spot.pos), t2, (t3) => {
        this.sit(t3, rnd(10, 25));
        if (spot.say) this.say(spot.say, t3 + 0.5, 2.4);
      });
    });
  }

  sit(t, dur) { this.mode = 'sit'; this.animT0 = t; this.until = t + dur; this.dir = 'down'; }

  goSleep(t) {
    const beds = CAT_BEDS.filter((b) => !b.sofa || !office.reserved.has(b.sofa));
    const bed = pick(beds);
    const lieDown = (t2) => { this.mode = 'sleep'; this.animT0 = t2; this.until = t2 + rnd(40, 100); this.bed = bed; this.nextMeow = t2 + rnd(3, 6); };
    if (bed.sofa) {
      office.reserved.set(bed.sofa, 'cat');
      this.goTo(bed.from, bed.node, t, (t2) => this.startJump(bed.pos, t2, lieDown));
    } else {
      this.goTo(bed.pos, bed.node, t, lieDown);
    }
  }

  // Подойти к демону и сесть рядом — тот обязательно отреагирует
  visitDemon(t) {
    const ws = [...office.workers.values()].filter((w) => w.visible && !w.lost && w.mode !== 'walk' && w.mode !== 'trans' &&
      w.place && !w.place.lounge && !w.place.exit);
    if (!ws.length) return false;
    const w = pick(ws);
    const side = w.mode === 'seated' ? (w.place.dir === 'right' ? -34 : 34) : 36;
    const pos = [w.pos[0] + side, w.pos[1] + (w.mode === 'seated' ? 10 : 4)];
    this.goTo(pos, w.place.node || nearestNode(pos), t, (t2) => {
      this.sit(t2, rnd(12, 22));
      if (!w.visible || w.mode === 'walk') return;
      w.sayLine(pick(CAT_LINES.greet), t2 + 0.4, 2.6);
      if (w.mode === 'stand') w.shot(Math.random() < 0.5 ? 'wave' : 'laugh', t2 + 0.4);
      else if (w.place && !WORKING.has(w.stage)) w.shot(w.seatedClip('talk'), t2 + 0.4);
      this.replies.push({ at: t2 + 2.8, text: pick(CAT_LINES.cat) });
    });
    return true;
  }

  update(dt, t) {
    while (this.replies.length && t >= this.replies[0].at) { const r = this.replies.shift(); this.say(r.text, t); }
    if (this.mode === 'jump') {
      const a = this.sheet.anims.jump, k = (t - this.jump.t0) * 1000 / a.total;
      if (k >= 1) { this.pos = [...this.jump.to]; const then = this.jump.then; this.jump = null; then(t); }
      else {
        const { from, to } = this.jump, e = clamp((k - 0.15) / 0.6, 0, 1);
        this.pos = [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
      }
      return;
    }
    if (this.path.length) {
      const [tx, ty] = this.path[0];
      const dx = tx - this.pos[0], dy = ty - this.pos[1], dist = Math.hypot(dx, dy), step = CAT_SPEED * dt;
      if (dist > 0.5) this.dir = Math.abs(dx) >= Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
      this.doorWait = doorBlocks(this.pos, this.path[0]);
      if (this.doorWait) return;
      if (dist <= step) {
        this.pos = [tx, ty]; this.path.shift();
        if (!this.path.length) { this.node = this.targetNode; this.mode = 'sit'; const cb = this.onArrive; this.onArrive = null; if (cb) cb(t); }
      } else {
        this.pos[0] += dx / dist * step; this.pos[1] += dy / dist * step;
      }
      // Демоны замечают кошку, когда она проходит мимо
      if (t >= this.nextGlance) {
        this.nextGlance = t + 1;
        for (const w of office.workers.values()) {
          if (!w.visible || w.lost || w.mode === 'walk' || (w.catCooldown || 0) > t) continue;
          if (Math.hypot(w.pos[0] - this.pos[0], w.pos[1] - this.pos[1]) > 80 || Math.random() > 0.3) continue;
          w.catCooldown = t + 40;
          if (!(w.speech && t < w.speech.until)) w.sayLine(pick(CAT_LINES.greet), t, 2.2);
        }
      }
      return;
    }
    if (t >= this.until) { this.decide(t); return; }
    if (t >= this.nextMeow) {
      if (this.mode === 'sleep') { this.say('z z z', t, 2.2); this.nextMeow = t + rnd(6, 11); }
      else { if (Math.random() < 0.3) this.say(pick(CAT_LINES.cat), t); this.nextMeow = t + rnd(6, 14); }
    }
  }

  // Демон подошёл погладить: кошка задерживается
  stay(t, sec) { this.until = Math.max(this.until, t + sec); }

  pose(t) {
    if (this.mode === 'jump') return ['jump', (t - this.jump.t0) * 1000, false];
    if (this.mode === 'walk' && this.doorWait) return ['idle', t * 1000, true];
    if (this.mode === 'walk') {
      const name = { left: 'walk-left', right: 'walk-right', down: 'walk-forward', up: 'walk-backward' }[this.dir];
      return [name, t * 1000, true];
    }
    if (this.mode === 'sleep') {
      const a = this.sheet.anims.sleep, ms = (t - this.animT0) * 1000;
      if (ms < a.total) return ['sleep', ms, false];
      return ['sleep', -1 - (Math.floor((ms - a.total) / 900) % 4), false]; // дыхание: кадры 3..6
    }
    return ['idle', (t - this.animT0) * 1000, true];
  }

  draw(g, t) {
    const [name, ms, loop] = this.pose(t);
    const a = this.sheet.anims[name] || this.sheet.anims.idle;
    let fr;
    if (ms < 0) fr = a.frames[Math.min(a.frames.length - 1, 3 + (-ms - 1))];
    else {
      let rest = loop ? ms % a.total : Math.min(ms, a.total - 1), i = 0;
      while (i < a.dur.length - 1 && rest >= a.dur[i]) { rest -= a.dur[i]; i++; }
      fr = a.frames[i];
    }
    const s = a.scale, top = fr.top || 0;
    g.save();
    g.imageSmoothingEnabled = office.scale * office.dpr * s < 1.4;
    g.drawImage(this.sheet.img, fr.sx, fr.sy + top, this.sheet.cw, this.sheet.ch - top,
      this.pos[0] - fr.ax * s, this.pos[1] - (fr.ay - top) * s, this.sheet.cw * s, (this.sheet.ch - top) * s);
    g.restore();
  }

  headY() {
    const name = this.pose(office.t)[0], a = this.sheet.anims[name] || this.sheet.anims.idle;
    return this.pos[1] - Math.min(a.height || 40, 48) - 4;
  }

  updateTag(t) {
    const tag = this.tag;
    const speaking = this.speech && t < this.speech.until;
    const bubble = tag.querySelector('.bubble'), text = speaking ? this.speech.text : '';
    if (bubble.textContent !== text) bubble.textContent = text;
    const sx = office.ox + this.pos[0] * office.scale, sy = office.oy + this.headY() * office.scale;
    const k = clamp(office.scale * 1.15, 0.65, 1.05);
    this.tagBox = { sx, sy, k, w: tag.offsetWidth * k, h: tag.offsetHeight * k };
    tag.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -100%) scale(${k})`;
    tag.style.zIndex = String(Math.round(this.pos[1]));
  }

  hit(px, py) { return Math.abs(px - this.pos[0]) < 30 && py > this.pos[1] - 48 && py < this.pos[1] + 6; }
}
