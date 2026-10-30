'use strict';
/* Тумба с ТВ и PlayStation (набор 08): анимации тумбы, игра и уборка приставки. */

// ------------------------------------------------------------------ тумба с ТВ и PlayStation (08)
// Одна приставка, два контроллера. Состояния тумбы: 0 закрыта, 2 открыта с приставкой, 3 открыта пустая,
// 5 приставка у ТВ (выкл), 6 игра, 7 пауза. Смена владельца — по событиям кадров клипов персонажа.
const cabinet = { img: null, frames: [], pos: [760, 665], ip: [845, 819], state: 0, seq: null, console: 'drawer', base: 800 };
const timers = [];
const after = (t, fn) => { timers.push({ at: t, fn }); timers.sort((a, b) => a.at - b.at); };
function runTimers(t) { while (timers.length && timers[0].at <= t) { const x = timers.shift(); try { x.fn(t); } catch (e) { console.error(e); } } }
function cabPlay(frames, durs, t, end) { cabinet.seq = { frames, durs, t0: t, end }; }
function cabFrame(t) {
  const q = cabinet.seq;
  if (q) {
    let ms = (t - q.t0) * 1000;
    for (let i = 0; i < q.frames.length; i++) { ms -= q.durs[i]; if (ms < 0) return q.frames[i]; }
    cabinet.state = q.end; cabinet.seq = null;
  }
  return cabinet.state;
}
function drawCabinet(g, t) {
  if (!cabinet.img) return;
  const f = cabinet.frames[cabFrame(t)] || cabinet.frames[0];
  g.imageSmoothingEnabled = false;
  g.drawImage(cabinet.img, f[0], f[1], f[2], f[3], cabinet.pos[0], cabinet.pos[1], f[2], f[3]);
}
// Время события клипа (мс от начала): кадр события = сумма длительностей предыдущих кадров
function eventMs(w, clip, name, fallback) {
  const a = w.char.anims[clip];
  if (!a) return fallback;
  const ev = (a.events || []).find((e) => e.name === name);
  return ev ? a.dur.slice(0, ev.frame).reduce((x, y) => x + y, 0) : fallback;
}
const clipMs = (w, clip, fallback) => (w.char.anims[clip] ? w.char.anims[clip].total : fallback);
const cabPlace = () => ({ key: 'cabinet', pos: cabinet.ip, node: 'cab_i', face: 'right', act: 'cab' });

// Достать приставку из ящика и подключить к ТВ (≈4.4 с)
function consoleSetup(w, t) {
  office.spots.add('cabinet');
  cabPlay([0, 1, 2], [120, 160, 220], t, 2);
  const t1 = t + 0.5;
  after(t1, (tt) => w.shot('retrieve_console_right', tt));
  after(t1 + eventMs(w, 'retrieve_console_right', 'console_pickup', 420) / 1000, () => { cabinet.console = 'carried'; cabinet.state = 3; cabinet.seq = null; });
  const t2 = t1 + clipMs(w, 'retrieve_console_right', 1600) / 1000;
  after(t2, (tt) => { cabPlay([3, 4, 0], [220, 160, 120], tt, 0); w.shot('set_console_right', tt); });
  after(t2 + eventMs(w, 'set_console_right', 'console_install', 700) / 1000, () => { cabinet.console = 'installed'; cabinet.state = 5; cabinet.seq = null; });
  after(t2 + clipMs(w, 'set_console_right', 1600) / 1000, () => office.spots.delete('cabinet'));
  return t2 + 1.7 - t;
}
// Снять приставку и убрать в ящик (≈4.2 с)
function consoleStore(w, t) {
  office.spots.add('cabinet');
  w.shot('take_installed_console_right', t);
  after(t + eventMs(w, 'take_installed_console_right', 'console_pickup_installed', 700) / 1000, () => { cabinet.console = 'carried'; cabinet.state = 0; });
  const t2 = t + clipMs(w, 'take_installed_console_right', 1600) / 1000;
  after(t2, (tt) => { cabPlay([0, 4, 3], [120, 160, 220], tt, 3); w.shot('return_console_right', tt); });
  after(t2 + eventMs(w, 'return_console_right', 'console_store', 700) / 1000, () => { cabinet.console = 'drawer'; cabinet.state = 2; cabinet.seq = null; });
  after(t2 + clipMs(w, 'return_console_right', 1600) / 1000, (tt) => { cabPlay([2, 1, 0], [220, 160, 120], tt, 0); office.spots.delete('cabinet'); });
  return t2 + 1.7 - t;
}

const seatPlaceOf = (l) => ({ key: 'lounge:' + l.key, kind: 'lounge', lounge: true, pos: l.pos, node: l.node, dir: l.dir,
  sit: true, feet: l.feet, furniture: l.furniture, act: 'coffee' });

// Игра вдвоём: один готовит приставку и садится в кресло, второй — на диван
ACTIVITIES.game = (a, t, all) => {
  if (!cabinet.img || office.game || office.spots.has('cabinet') || cabinet.console === 'carried') return false;
  const b = all.find((w) => w !== a && w.char.anims.sofa_game_left);
  const arm = LOUNGE.find((l) => l.key === 'arm');
  const sofa = ['sofa2', 'sofa1'].map((k) => LOUNGE.find((l) => l.key === k)).find((l) => !office.reserved.has(l.key));
  if (!b || !a.char.anims.armchair_game_right || office.reserved.has('arm') || !sofa) return false;
  office.reserved.set('arm', a.id); office.reserved.set(sofa.key, b.id);
  const game = office.game = { players: [a, b], done: false, playing: false, endAt: 0 };
  const legsA = [];
  if (cabinet.console === 'drawer') {
    legsA.push({ place: cabPlace(), dur: 4.6, say: pick(LINES.gameStart), onArrive: (tt) => consoleSetup(a, tt) });
  }
  legsA.push({ place: seatPlaceOf(arm), dur: 999, conv: true });
  if (Math.random() < 0.6) legsA.push({ place: cabPlace(), dur: 4.4, onArrive: (tt) => { if (cabinet.console === 'installed' && !office.spots.has('cabinet')) consoleStore(a, tt); } });
  a.startPlan('game', legsA, t, { conv: game });
  b.startPlan('game', [{ place: seatPlaceOf(sofa), dur: 999, conv: true }], t, { conv: game });
  if (cabinet.console !== 'drawer') a.sayLine(pick(LINES.gameStart), t, 2.4);
  return true;
};
// Убрать приставку, если её оставили у ТВ
ACTIVITIES.tidy = (a, t) => {
  if (!cabinet.img || cabinet.console !== 'installed' || office.game || office.spots.has('cabinet')) return false;
  a.startPlan('tidy', [{ place: cabPlace(), dur: 4.4, say: 'Уберу приставку на место',
    onArrive: (tt) => { if (cabinet.console === 'installed' && !office.game) consoleStore(a, tt); } }], t);
  return true;
};

function updateGame(t) {
  const game = office.game;
  if (!game) return;
  const inSession = game.players.filter((w) => w.plan && w.plan.conv === game);
  if (game.done || inSession.length < 2) {
    if (game.playing) { cabinet.state = 5; game.playing = false; }
    game.players.forEach((w) => { w.gaming = false; });
    game.done = true;
    if (!inSession.length) office.game = null;
    return;
  }
  const seated = game.players.every((w) => w.mode === 'seated' && w.place && w.place.furniture);
  if (!game.playing && seated && cabinet.console === 'installed' && !office.spots.has('cabinet')) {
    game.playing = true; cabinet.state = 6; game.endAt = t + rnd(25, 45);
    game.players.forEach((w) => { w.gaming = true; w.nextAct = t + rnd(3, 8); });
    game.players[0].sayLine('Погнали!', t, 1.8);
  }
  if (game.playing && t > game.endAt) {
    game.playing = false; cabinet.state = 7;
    after(t + 1.2, () => { if (cabinet.state === 7) cabinet.state = 5; });
    game.players.forEach((w) => { w.gaming = false; });
    const [w1, w2] = game.players;
    w1.sayLine(pick(['Хорошая игра!', 'Ладно, твоя взяла', 'Реванш потом']), t, 2.4);
    w2.replies.push({ at: t + 2.4, text: pick(['GG', 'Обращайся :)', 'Договорились']) });
    after(t + 3.5, () => { game.done = true; });
  }
}
