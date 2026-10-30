'use strict';
/* Персонаж-демон: ходьба по графу, этапы работы (стол, принтер, переговорка, доска), реплики. */

class Worker {
  constructor(d, slot) {
    this.id = d.id; this.slot = slot;
    this.char = charFor(d, slot);
    this.seat = slot < SEATS.length ? SEATS[slot] : null;
    this.pos = [...N.door_out]; this.node = 'door_out'; this.place = null; this.target = null;
    this.speed = 0; this.walkClock = 0;
    this.visible = false; this.path = []; this.dir = 'down';
    this.mode = 'stand';      // walk | stand | seated | trans
    this.trans = null;        // текущий переход sit_down / stand_up
    this.oneShot = null;      // разовое действие: кофе, приветствие, празднование
    this.pending = null;      // место, куда идти после перехода
    this.queue = []; this.step = null; this.arrivedAt = null; this.nextAct = 0;
    this.lastEventT = 0; this.data = d; this.cheerUntil = 0;
    this.plan = null;         // занятие в простое: разговор, диван, кулер, прогулка…
    this.restUntil = 0;       // до какого времени просто сидеть за столом
    this.speech = null;       // реплика в бабле { text, until }
    this.replies = [];        // отложенные ответы в диалоге { at, text, pose }
    this.tag = document.createElement('div'); this.tag.className = 'tag';
    this.tag.innerHTML = '<div class="bubble"></div><div class="name"><i class="dot"></i><span></span></div>';
    $('tags').appendChild(this.tag);
  }

  // --- места
  seatPlace() {
    if (!this.seat) return this.loungePlace();
    const s = this.seat;
    return { key: 'seat:' + s.key, kind: 'seat', pos: s.pos, node: s.node, dir: s.dir, sit: true };
  }

  loungePlace() {
    let spot = LOUNGE.find((l) => office.reserved.get(l.key) === this.id);
    if (!spot) spot = LOUNGE.find((l) => !office.reserved.has(l.key)) || LOUNGE[this.slot % LOUNGE.length];
    office.reserved.set(spot.key, this.id);
    return { key: 'lounge:' + spot.key, kind: 'lounge', lounge: true, pos: spot.pos, node: spot.node,
      dir: spot.dir, sit: !!spot.sit, face: 'down', act: 'coffee', feet: spot.feet, furniture: spot.furniture };
  }

  release(exceptKey) {
    for (const [k, v] of office.reserved) if (v === this.id && 'lounge:' + k !== exceptKey) office.reserved.delete(k);
  }

  placeFor(stage) {
    const s = this.slot;
    switch (stage) {
      case 'starting': case 'generating': case 'rework': case 'reviewing': case 'retro': case 'error': case 'idle': return this.seatPlace();
      case 'git': if (s >= PRINTER.length) return this.seatPlace(); return { key: 'printer', pos: PRINTER[s % PRINTER.length], node: 'pr_s', face: 'down', act: 'printer' };
      case 'jenkins': {
        if (s >= MEET.length) return this.seatPlace();
        const p = MEET[s % MEET.length];
        return { key: 'meeting', pos: p, node: p[0] < 900 ? 'meet_w' : 'meet_e', face: 'down', act: 'talk' };
      }
      case 'jira': case 'exploring': if (s >= BOARD.length) return this.seatPlace(); return { key: 'board', pos: BOARD[s % BOARD.length], node: 'board', face: 'up', act: 'think' };
      case 'stopped': return { key: 'door', pos: N.door_out, node: 'door_out', exit: true };
      case '_greet': case '_bye': return { key: 'door_in', pos: N.door_in, node: 'door_in', face: 'down', act: 'wave' };
      default: return null; // polling, success — остаться на месте
    }
  }

  // --- данные с сервера
  ingest(d, first) {
    this.data = d;
    const events = (d.events || []).filter((e) => e.t > this.lastEventT);
    const lastT = Math.max(this.lastEventT, ...(d.events || []).map((e) => e.t), d.stage_since || 0);
    this.lastEventT = lastT;
    if (first) {
      if (d.stage === 'stopped') return;
      const current = { stage: d.stage, issue: d.issue, ...(d.detail || {}), t: d.stage_since };
      if (d.stage === 'starting' && nowSec() - d.stage_since < 15) this.enqueue(current);
      else this.teleport(current);
      return;
    }
    for (const e of events) this.enqueue(e);
  }

  enqueue(e) {
    if (e.stage === 'polling') office.tvStart = office.t;
    this.queue.push(e);
    if (this.queue.length > 4) this.queue.splice(0, this.queue.length - 4);
  }

  // Дашборд открыт посреди работы: сразу ставим персонажа на место, без анимации прихода
  teleport(e) {
    const stage = e.stage === 'success' || e.stage === 'polling' ? 'idle' : e.stage;
    const place = this.placeFor(stage) || this.seatPlace();
    this.visible = true; this.step = e; this.pos = [...place.pos]; this.node = place.node; this.path = [];
    this.place = place; this.arrivedAt = office.t;
    if (place.sit) { this.mode = 'seated'; this.dir = place.dir; if (place.feet) this.pos = [...place.feet]; }
    else { this.mode = 'stand'; this.dir = place.face || 'down'; }
    if (stage === 'idle') this.restUntil = office.t + rnd(1, 10);
    this.nextAct = office.t + 2 + Math.random() * 6;
  }

  begin(e, t) {
    if (this.plan) {
      // Опрос и «ждёт задач» не прерывают занятие; реальная работа — прерывает
      if (e.stage === 'idle' || e.stage === 'polling') { this.step = e; this.arrivedAt = t; return; }
      this.endPlan(t, true);
    }
    if (e.stage === 'idle') this.restUntil = t + rnd(...REST_AT_DESK);
    this.step = e; this.arrivedAt = null;
    if (e.stage === 'stopped') {
      if (!this.visible) { this.arrivedAt = t; return; }
      if (!e._bye) { this.queue.unshift({ ...e, _bye: true }); e = this.step = { stage: '_bye', t: e.t }; }
    } else if (!this.visible) {
      // Входит через двери, машет и идёт к месту
      this.visible = true; this.pos = [...N.door_out]; this.node = 'door_out';
      this.place = null; this.mode = 'stand'; this.dir = 'up';
      this.queue.unshift(e); e = this.step = { stage: '_greet', t: e.t };
      office.react(this, t, 'greet');
    }
    if (e.stage === 'success') { this.cheerUntil = t + 3.2; office.react(this, t, 'success'); }
    const place = this.placeFor(e.stage);
    if (!place) {
      this.arrivedAt = t;
      if (e.stage === 'success' && this.mode === 'stand') this.shot('celebrate', t);
      return;
    }
    this.goTo(place, t);
  }

  goTo(place, t) {
    if (this.mode === 'trans') { this.pending = place; return; }
    if (this.place && this.place.key === place.key && !this.path.length) { this.arrive(place, t, true); return; }
    if (this.mode === 'seated' && this.place && this.place.sit) {
      const dir = this.place.dir, from = this.place;
      this.oneShot = null; this.gaming = false;
      const name = from.furniture ? `${from.furniture}_stand_${dir}` : `stand_up_${dir}`;
      this.startTrans(name, t, (t2) => { this.mode = 'stand'; this.dir = dir; this.walkTo(place, t2); },
        from.feet ? { from: [...from.feet], to: [...from.pos] } : null);
      return;
    }
    this.walkTo(place, t);
  }

  walkTo(place, t) {
    this.release(place.key);
    // Смена цели на ходу: строим путь от ближайшего узла, а не возвращаемся к прошлому
    if (this.mode === 'walk') this.node = nearestNode(this.pos);
    const nodes = route(this.node, place.node).map((n) => N[n]);
    this.path = [...nodes, place.pos];
    if (this.mode !== 'walk') this.speed = 0;
    this.target = place; this.place = null; this.mode = 'walk'; this.oneShot = null;
  }

  arrive(place, t, already) {
    this.place = place; this.node = place.node; this.path = [];
    if (place.exit) { this.visible = false; this.mode = 'stand'; this.arrivedAt = t; this.release(); return; }
    if (place.sit) {
      if (already && this.mode === 'seated') { this.arrivedAt = t; return; }
      this.dir = place.dir;
      // Диван и кресло — свои посадки (08): с точки подхода корень плавно уходит на место сидения
      const name = place.furniture ? `${place.furniture}_sit_${place.dir}` : `sit_down_${place.dir}`;
      this.startTrans(name, t, (t2) => {
        this.mode = 'seated'; this.arrivedAt = t2; this.nextAct = t2 + 4 + Math.random() * 6;
      }, place.feet ? { from: [...place.pos], to: place.feet } : null);
      return;
    }
    if (!already || this.mode !== 'stand') this.oneShot = null;
    this.mode = 'stand'; this.dir = place.face || 'down'; this.arrivedAt = t; this.nextAct = t + 0.5;
    if (place.act === 'printer') office.printerStart = t;
    if (place.act === 'wave') this.shot('wave', t);
  }

  // ---- занятия в простое
  get free() {
    return this.visible && !this.lost && this.step && this.step.stage === 'idle' && !this.plan && !this.queue.length &&
      !this.path.length && this.mode !== 'trans' && this.mode !== 'walk' && this.arrivedAt !== null;
  }

  sayLine(text, t, dur = 2.4) { this.speech = { text, until: t + dur }; }
  // Клип сидя по типу мебели: офисный стул (06) или диван/кресло (08)
  seatedClip(kind) {
    const f = this.place && this.place.furniture, d = this.place ? this.place.dir : 'right';
    if (f && this.char.anims[`${f}_idle_${d}`]) {
      return `${f}_${{ coffee: 'drink', talk: 'talk', laugh: 'laugh', idle: 'idle', game: 'game', win: 'game_win' }[kind] || 'idle'}_${d}`;
    }
    return { coffee: `seated_coffee_${d}`, talk: `seated_talk_${d}`, laugh: `seated_talk_${d}` }[kind] || `seated_idle_${d}`;
  }
  talkPose() { return this.mode === 'seated' && this.place ? this.seatedClip('talk') : 'talk'; }
  laughPose() { return this.mode === 'seated' && this.place ? this.seatedClip('laugh') : 'laugh'; }
  // Мысль вслух: для стоящего — с анимацией размышления
  muse(t) { this.sayLine(pick(SOLO), t, 2.8); if (this.mode === 'stand') this.shot('think', t); }

  startPlan(kind, legs, t, extra = {}) {
    this.plan = { kind, legs, i: -1, legT: null, ...extra };
    this.nextLeg(t);
  }

  nextLeg(t) {
    const plan = this.plan;
    plan.i++; plan.legT = null;
    if (plan.i >= plan.legs.length) { this.endPlan(t, false); return; }
    const leg = plan.legs[plan.i];
    if (!this.visible && !leg.place.exit) {
      // Возвращается с прогулки
      this.visible = true; this.pos = [...N.door_out]; this.node = 'door_out'; this.place = null; this.mode = 'stand';
    }
    if (leg.say) this.sayLine(leg.say, t, 2.4);
    this.goTo(leg.place, t);
  }

  endPlan(t, interrupted) {
    const plan = this.plan;
    if (!plan) return;
    this.plan = null;
    if (plan.conv) plan.conv.done = true;
    if (plan.spot) office.spots.delete(plan.spot);
    this.restUntil = t + rnd(...REST_AT_DESK);
    if (!interrupted) this.goTo(this.seatPlace(), t);
  }

  // true — занятие управляет персонажем в этом кадре
  runPlan(t) {
    const plan = this.plan, leg = plan.legs[plan.i];
    if (!leg) return false;
    const there = this.place && this.place.key === leg.place.key && this.mode !== 'trans' && !this.path.length;
    if (!there && !(leg.place.exit && !this.visible)) return true;
    if (plan.legT === null) { plan.legT = t; if (leg.onArrive) leg.onArrive(t); }
    if (plan.conv && plan.conv.done && leg.conv) { this.nextLeg(t); return true; }
    if (leg.tick) leg.tick(t);
    if (t - plan.legT >= leg.dur) { this.nextLeg(t); return true; }
    return !this.visible || leg.place.act === 'chat';
  }

  startTrans(name, t, then, lerp) {
    if (!this.char.anims[name]) { if (lerp) this.pos = [...lerp.to]; then(t); return; }
    this.mode = 'trans'; this.trans = { name, t0: t, then, lerp };
  }

  shot(name, t) { if (this.char.anims[name]) this.oneShot = { name, t0: t }; }
  shotActive(t) { return !!this.oneShot && (t - this.oneShot.t0) * 1000 < (this.char.anims[this.oneShot.name] || { total: 0 }).total; }

  dwell(stage) {
    if (stage === 'polling' || stage === 'idle' || stage === 'starting') return 0;
    if (stage === '_greet' || stage === '_bye') return 1.3;
    if (stage === 'success') return 3.2;
    return MIN_DWELL;
  }

  update(dt, t) {
    if (this.mode === 'trans') {
      const a = this.char.anims[this.trans.name], k = (t - this.trans.t0) * 1000 / a.total;
      const lerp = this.trans.lerp;
      if (lerp) {
        // смещение корня в первые ~70% клипа (до касания сиденья), без телепортации
        const e = clamp(k / 0.7, 0, 1), ee = e * e * (3 - 2 * e);
        this.pos = [lerp.from[0] + (lerp.to[0] - lerp.from[0]) * ee, lerp.from[1] + (lerp.to[1] - lerp.from[1]) * ee];
      }
      if (k >= 1) {
        if (lerp) this.pos = [...lerp.to];
        const then = this.trans.then; this.trans = null; then(t);
        if (this.pending && this.mode !== 'trans') { const p = this.pending; this.pending = null; this.goTo(p, t); }
      }
      return;
    }
    const settled = this.arrivedAt !== null && !this.path.length;
    if (!this.step || (this.queue.length && settled && t - this.arrivedAt >= this.dwell(this.step.stage))) {
      const next = this.queue.shift();
      if (next) this.begin(next, t);
    }
    if (this.path.length) {
      const [tx, ty] = this.path[0];
      const dx = tx - this.pos[0], dy = ty - this.pos[1], dist = Math.hypot(dx, dy);
      const desired = this.path.length === 1 ? Math.min(SPEED, Math.max(18, dist * 5)) : SPEED;
      this.speed += (desired - this.speed) * (1 - Math.exp(-10 * dt));
      const stepLen = this.speed * dt;
      this.walkClock += dt * this.speed / SPEED;
      if (dist > 0.5) this.dir = Math.abs(dx) >= Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
      // Перед дверью кабинета/переговорки ждём, пока она откроется полностью
      this.doorWait = doorBlocks(this.pos, this.path[0]);
      if (this.doorWait) { this.speed = 0; return; }
      if (dist <= stepLen) {
        this.pos = [tx, ty]; this.path.shift();
        if (!this.path.length) this.arrive(this.target, t);
      } else {
        this.pos[0] += dx / dist * stepLen; this.pos[1] += dy / dist * stepLen;
      }
      return;
    }
    const st = this.step && this.step.stage;
    // Отложенные ответы в диалоге
    while (this.replies.length && t >= this.replies[0].at) {
      const r = this.replies.shift();
      if (!this.lost && this.visible) { this.shot(r.pose || this.talkPose(), t); this.sayLine(r.text, t, r.dur || 2.4); }
    }
    if (this.plan && this.lost) this.endPlan(t, true);
    if (this.plan && this.runPlan(t)) return;
    // Мелкие действия на месте: глоток кофе сидя, разговор на диване, кофе стоя
    if (t >= this.nextAct && !this.shotActive(t) && !this.lost) {
      if (this.mode === 'seated' && this.place) {
        const lounge = this.place.lounge, gen = WORKING.has(st);
        const neighbour = lounge && [...office.workers.values()].find((w) => w !== this && w.mode === 'seated' &&
          w.place && w.place.lounge && !w.replies.length && !w.shotActive(t));
        if (this.gaming) { if (Math.random() < 0.35) { this.shot(this.seatedClip('win'), t); this.sayLine(pick(LINES.game), t, 2); } }
        else if (neighbour && !neighbour.gaming && Math.random() < 0.6) dialog(this, neighbour, t);
        else if (lounge && Math.random() < 0.35) { this.shot(this.seatedClip('coffee'), t); this.sayLine(pick(SOLO), t + 1, 2.8); }
        else if (lounge || st === 'idle' || (gen && Math.random() < 0.4)) this.shot(this.seatedClip('coffee'), t);
        if (!lounge && st === 'idle' && Math.random() < 0.25) this.muse(t);
        this.nextAct = t + (lounge ? rnd(6, 11) : rnd(18, 43));
      } else if (this.mode === 'stand' && this.place && this.place.act === 'coffee') {
        if (Math.random() < 0.4) this.muse(t); else this.shot('coffee', t);
        this.nextAct = t + rnd(4, 8);
      } else if (this.mode === 'stand' && this.place && this.place.act === 'look') {
        if (Math.random() < 0.5) this.muse(t);
        this.nextAct = t + rnd(4, 7);
      } else {
        this.nextAct = t + 2;
      }
    }
  }

  get lost() { return this.data.alive === false && this.data.stage !== 'stopped'; }
  get stage() {
    if (this.lost) return 'lost';
    const s = this.step ? this.step.stage : this.data.stage;
    return s === '_greet' ? 'starting' : s === '_bye' ? 'stopped' : s;
  }

  // [имя анимации, время в мс, цикл]
  pose(t) {
    const off = this.slot * 173;
    if (this.mode === 'trans') return [this.trans.name, (t - this.trans.t0) * 1000, false];
    if (this.mode === 'walk') return this.doorWait ? [`idle_${this.dir}`, t * 1000 + off, true] : [`walk_${this.dir}`, this.walkClock * 1000 + off, true];
    if (this.lost) return [this.mode === 'seated' && this.place ? this.seatedClip('idle') : `idle_${this.dir}`, 0, false];
    if (this.shotActive(t)) return [this.oneShot.name, (t - this.oneShot.t0) * 1000, false];
    const loopT = t * 1000 + off;
    if (this.mode === 'seated' && this.place) {
      const d = this.place.dir;
      if (this.place.furniture && this.char.anims[`${this.place.furniture}_idle_${d}`]) {
        return [this.seatedClip(this.gaming ? 'game' : 'idle'), loopT, true];
      }
      if (this.place.lounge) return [`lounge_${d}`, loopT, true];
      if (WORKING.has(this.stage)) return [`work_${d}`, loopT, true];
      return [`seated_idle_${d}`, loopT, true];
    }
    const act = this.place && this.place.act;
    if (act === 'talk') return ['talk', loopT, true];
    if (act === 'chat' || act === 'look') return [`idle_${this.dir}`, loopT, true];
    if (act === 'think') return ['think', loopT, true];
    return [`idle_${this.dir}`, loopT, true];
  }

  // --- отрисовка
  draw(g, t) {
    if (!this.visible) return;
    const ch = this.char;
    const [name, ms, loop] = this.pose(t);
    const a = ch.anims[name] || ch.anims.idle_down;
    const i = frameIndex(a, ms, loop);
    const [x, y] = this.pos, s = CHAR_SCALE;
    g.save();
    if (this.id === office.selected) {
      g.fillStyle = 'rgba(94, 234, 212, 0.35)';
      g.beginPath(); g.ellipse(x, y - 2, 26, 9, 0, 0, Math.PI * 2); g.fill();
    }
    if (this.lost) { g.globalAlpha = 0.55; if (filterSupported) g.filter = 'grayscale(1)'; }
    // Пиксель-арт: при увеличении — без сглаживания, при сильном уменьшении — со сглаживанием
    g.imageSmoothingEnabled = office.scale * office.dpr * s < 1.4;
    const cell = a.cells[i];
    const img = a.img || ch.img, px = a.px ?? ch.px, py = a.py ?? ch.py;
    const sx = cell.sx ?? cell.col * ch.fw, sy = cell.sy ?? cell.row * ch.fh, sw = cell.sw ?? ch.fw, sh = cell.sh ?? ch.fh;
    const reaction = reactionOffset(this,t);
    g.translate(x + reaction[0], y + (cell.dy || 0) * s + reaction[1]);
    if (cell.flip) g.scale(-1, 1);
    const look = appearanceFrame(img, sx, sy, sw, sh, ch.id, this.data.appearance || 0);
    if (look) g.drawImage(look, 0, 0, sw, sh, -px * s, -py * s, sw * s, sh * s);
    else g.drawImage(img, sx, sy, sw, sh, -px * s, -py * s, sw * s, sh * s);
    g.restore();
    drawReaction(this,g,t);
  }

  headY() {
    return this.pos[1] - (this.mode === 'seated' ? (this.place && this.place.furniture ? 80 : 90) : STAND_H + 2);
  }

  updateTag(t) {
    const tag = this.tag;
    if (!this.visible) { tag.style.display = 'none'; this.tagBox = null; return; }
    tag.style.display = '';
    const stage = this.stage, info = STAGE[stage] || STAGE.idle, d = this.data, step = this.step || {};
    tag.style.setProperty('--c', info.color);
    tag.className = 'tag ' + stage + (this.id === office.selected ? ' sel' : '');
    const label = displayName(d) + (d.guest ? ' · в гостях' : '');
    const nameEl = tag.querySelector('.name span');
    if (nameEl.textContent !== label) nameEl.textContent = label;
    const since = (step.t || d.stage_since || nowSec());
    let text = '';
    switch (step.stage === '_greet' || step.stage === '_bye' ? step.stage : stage) {
      case '_greet': text = 'привет!'; break;
      case '_bye': text = 'до встречи!'; break;
      case 'generating': text = `${step.issue || d.issue || ''} · пишет код ${fmtDur(nowSec() - since)}`; break;
      case 'reviewing': text = `${step.issue || d.issue || ''} · ревью ${fmtDur(nowSec() - since)}`; break;
      case 'rework': text = `${step.issue || d.issue || ''} · доработка ${fmtDur(nowSec() - since)}`; break;
      case 'exploring': text = `${step.issue || d.issue || ''} · изучает бэклог`; break;
      case 'retro': text = 'вспоминает свои задачи…'; break;
      case 'git': text = `git push ${(step.branch || '').split('/').pop() || step.issue || ''}`; break;
      case 'jenkins': text = `деплой → ${step.stand || '?'}${step.migration ? ' + миграция' : ''}`; break;
      case 'jira': text = `${step.issue || ''} → ${(step.targets || []).join(' / ') || 'статус'}`; break;
      case 'success': text = (step.result === 'warn' ? '⚠ ' : '✓ ') + (step.issue || 'готово'); break;
      case 'error': text = `✗ ${step.issue || 'ошибка'}`; break;
      case 'lost': text = `нет сигнала ${fmtDur(d.heartbeat_age || 0)}`; break;
      case 'polling': text = 'смотрит Jira…'; break;
      case 'starting': text = 'запуск'; break;
      case 'idle': {
        const idle = idleSeconds(d);
        text = this.place && this.place.lounge && idle != null ? `☕ простой ${fmtIdle(idle)}` : '';
        break;
      }
    }
    if (stage === 'success' && t > this.cheerUntil + 6) text = '';
    const speaking = this.speech && t < this.speech.until;
    if (speaking) text = this.speech.text;
    tag.classList.toggle('say', !!speaking);
    const bubble = tag.querySelector('.bubble');
    if (bubble.textContent !== text) bubble.textContent = text;
    const sx = office.ox + this.pos[0] * office.scale, sy = office.oy + this.headY() * office.scale;
    const k = clamp(office.scale * 1.25, 0.7, 1.15);
    this.tagBox = { sx, sy, k, w: tag.offsetWidth * k, h: tag.offsetHeight * k };
    tag.style.zIndex = String(Math.round(this.pos[1]));
  }

  hit(px, py) {
    if (!this.visible) return false;
    const top = this.pos[1] - (this.mode === 'seated' ? 92 : STAND_H);
    return Math.abs(px - this.pos[0]) < 30 && py > top - 10 && py < this.pos[1] + 6;
  }

  destroy() { this.release(); this.tag.remove(); }
}
