'use strict';
/* Жизнь офиса в простое: занятия (диван, кухня, окно, разговоры, визиты), диалоги, реакции. */

// ------------------------------------------------------------------ жизнь офиса в простое
const standPlace = (key, pos, face, act, node) => ({ key, pos, node: node || nearestNode(pos), face, act });

function outsideLegs(w, dur) {
  return [
    { place: { key: 'door', pos: N.door_out, node: 'door_out', exit: true }, dur, say: pick(LINES.out) },
    { place: { key: 'door_in', pos: N.door_in, node: 'door_in', face: 'down', act: 'wave' }, dur: 1.4,
      onArrive: (t) => { w.shot('wave', t); w.sayLine(pick(LINES.back), t, 2); } },
  ];
}

const ACTIVITIES = {
  // Разговор вдвоём: по очереди говорят, иногда смеются; бывает, потом вместе выходят прогуляться
  chat(a, t, all) {
    const b = all.find((w) => w !== a);
    const spot = CHAT_SPOTS.findIndex((_, i) => !office.spots.has('chat' + i));
    if (!b || spot < 0) return false;
    const [cx, cy] = CHAT_SPOTS[spot], dur = rnd(14, 26), key = 'chat' + spot;
    office.spots.add(key);
    const conv = { done: false, next: 0, speaker: 1, members: [a, b] };
    const tick = (tt) => {
      if (conv.members.some((m) => !m.plan || m.plan.conv !== conv || m.plan.legT === null)) return;
      if (tt < conv.next) return;
      // По очереди задают вопрос — второй отвечает; иногда смеются вместе
      conv.speaker = 1 - conv.speaker;
      const r = Math.random();
      // Парные жесты из 08: дружеский хлопок по плечу и передача посылки (a смотрит вправо, b — влево)
      if (r < 0.14 && a.char.anims.pat_shoulder_right && b.char.anims.pat_received_left) {
        const [q, ans] = pick(LINES.pat);
        a.shot('pat_shoulder_right', tt); b.shot('pat_received_left', tt); a.sayLine(q, tt, 2.4);
        b.replies.push({ at: tt + 1.5, text: ans, pose: 'pat_received_left', dur: 2 });
        conv.next = tt + 5.5; return;
      }
      if (r < 0.24 && a.char.anims.give_item_right && b.char.anims.receive_item_left) {
        const [q, ans] = pick(LINES.give);
        a.shot('give_item_right', tt); b.shot('receive_item_left', tt); a.sayLine(q, tt, 2.4);
        b.replies.push({ at: tt + 1.6, text: ans, pose: 'idle_left', dur: 2 });
        conv.next = tt + 5.5; return;
      }
      const [x, y] = conv.speaker ? [b, a] : [a, b];
      const laughs = dialog(x, y, tt);
      conv.next = tt + (laughs ? 8 : 5.8) + rnd(0, 1.5);
    };
    const together = Math.random() < 0.3;
    const legsFor = (w, dx, face) => {
      const legs = [{ place: standPlace(`${key}:${face}`, [cx + dx, cy], face, 'chat'), dur, conv: true, tick: w === a ? tick : null }];
      return together ? legs.concat(outsideLegs(w, rnd(25, 45))) : legs;
    };
    a.startPlan('chat', legsFor(a, -22, 'right'), t, { conv, spot: key });
    b.startPlan('chat', legsFor(b, 22, 'left'), t, { conv });
    return true;
  },
  // Отдых на диване или в кресле
  sofa(a, t) {
    a.startPlan('sofa', [{ place: a.loungePlace(), dur: rnd(20, 45) }], t);
    return true;
  },
  // Кофе у кулера
  cooler(a, t) {
    if (office.spots.has('cooler')) return false;
    office.spots.add('cooler');
    a.startPlan('cooler', [{ place: standPlace('cooler', COOLER, 'up', 'coffee'), dur: rnd(8, 14),
      onArrive: (tt) => a.shot('coffee', tt) }], t, { spot: 'cooler' });
    return true;
  },
  // Кофе на кухне: тумба с кофемашиной и снеками у кулера
  kitchen(a, t) {
    if (office.spots.has('kitchen') || !office.decor.coffee) return false;
    office.spots.add('kitchen');
    a.startPlan('kitchen', [{ place: standPlace('kitchen', KITCHEN, 'up', 'coffee', 'mgr_door'), dur: rnd(9, 16),
      onArrive: (tt) => { a.shot('coffee', tt); if (Math.random() < 0.5) a.sayLine(pick(['Сначала кофе, потом код', 'Где мой кофе?', 'Кто доел печеньки?', 'Кофемашина опять пустая']), tt + 0.5, 2.6); } }],
    t, { spot: 'kitchen' });
    return true;
  },
  // Постоять у окна
  window(a, t) {
    const i = WINDOWS.findIndex((_, k) => !office.spots.has('win' + k));
    if (i < 0) return false;
    office.spots.add('win' + i);
    a.startPlan('window', [{ place: standPlace('win' + i, WINDOWS[i], 'down', 'look'), dur: rnd(8, 15),
      onArrive: (tt) => a.shot('think', tt) }], t, { spot: 'win' + i });
    return true;
  },
  // Заглянуть к коллеге, который пишет код; тот оборачивается и отвечает
  visit(a, t) {
    const target = [...office.workers.values()].find((w) => w !== a && w.visible && w.seat && w.mode === 'seated' &&
      WORKING.has(w.stage) && !office.spots.has('visit:' + w.id));
    if (!target) return false;
    const key = 'visit:' + target.id, seatNode = N[target.seat.node];
    office.spots.add(key);
    const face = target.seat.pos[1] > seatNode[1] ? 'down' : 'up';
    let next = 0;
    a.startPlan('visit', [{ place: standPlace(key, seatNode, face, 'chat'), dur: rnd(7, 11),
      onArrive: (tt) => { a.shot('wave', tt); next = tt + 1.3; },
      tick: (tt) => {
        if (tt < next || target.mode !== 'seated') return;
        dialog(a, target, tt, VISIT_DIALOGS);
        next = tt + 99; // один обмен репликами, потом уходит
      } }], t, { spot: key });
    return true;
  },
  // Выйти из офиса и вернуться
  outside(a, t) {
    const next = a.data.next_poll_at || (a.data.detail || {}).next_poll_at;
    if (next && next - nowSec() < 50) return false;
    a.startPlan('outside', outsideLegs(a, rnd(25, 60)), t);
    return true;
  },
};
// Подойти к Кокошке: погладить или полюбоваться, как спит
ACTIVITIES.cat = (a, t) => {
  const cat = office.cat;
  if (!cat || !cat.resting || office.spots.has('cat')) return false;
  office.spots.add('cat');
  const dx = cat.pos[0] > 640 ? -40 : 40;
  const sleeping = cat.mode === 'sleep';
  cat.stay(t, 30);
  a.startPlan('cat', [{ place: standPlace('cat', [cat.pos[0] + dx, cat.pos[1] + 4], dx > 0 ? 'left' : 'right', 'chat', cat.node),
    dur: rnd(6, 10),
    onArrive: (tt) => {
      cat.stay(tt, 10);
      a.sayLine(pick(sleeping ? CAT_LINES.sleep : CAT_LINES.greet), tt, 2.6);
      a.shot(sleeping ? 'think' : (Math.random() < 0.5 ? 'laugh' : 'wave'), tt);
      if (!sleeping) cat.replies.push({ at: tt + 2.4, text: pick(CAT_LINES.cat) });
    } }], t, { spot: 'cat' });
  return true;
};
const ACTIVITY_WEIGHTS = { game: 2.4, tidy: 3, cat: 1.6, chat: 4.5, sofa: 3, kitchen: 2, cooler: 1.2, visit: 2, window: 1.2, outside: 1.3 };

// Мини-диалог: a спрашивает, b отвечает через паузу, иногда потом оба смеются. Возвращает true, если смеялись
function dialog(a, b, t, pool = DIALOGS) {
  const [q, ans] = pick(pool);
  a.shot(a.talkPose(), t); a.sayLine(q, t, 2.5);
  b.replies.push({ at: t + 2.6, text: ans });
  if (Math.random() < 0.35) {
    a.replies.push({ at: t + 5.2, text: pick(LINES.laugh), pose: a.laughPose(), dur: 1.8 });
    b.replies.push({ at: t + 5.4, text: pick(LINES.laugh), pose: b.laughPose(), dur: 1.8 });
    return true;
  }
  return false;
}

// Раз в секунду: свободные (ждут задач и отдохнули за столом) выбирают занятие
function planIdle(t) {
  if (t < office.nextPlan) return;
  office.nextPlan = t + 1;
  const free = [...office.workers.values()].filter((w) => w.free).sort(() => Math.random() - 0.5);
  for (const w of free) {
    if (!w.free || t < w.restUntil) continue;
    const others = free.filter((o) => o !== w && o.free && t >= o.restUntil - 6);
    const kinds = Object.keys(ACTIVITY_WEIGHTS).filter((k) => k !== 'chat' || others.length);
    for (let attempt = 0; attempt < 4; attempt++) {
      let r = Math.random() * kinds.reduce((s, k) => s + ACTIVITY_WEIGHTS[k], 0), kind = kinds[0];
      for (const k of kinds) { r -= ACTIVITY_WEIGHTS[k]; if (r <= 0) { kind = k; break; } }
      if (ACTIVITIES[kind](w, t, [w, ...others])) break;
    }
  }
}

// Коллеги реагируют: машут вошедшему, радуются закрытой задаче
office.react = (who, t, why) => {
  for (const w of office.workers.values()) {
    if (w === who || !w.visible || w.lost || w.mode === 'walk' || w.mode === 'trans' || Math.random() < 0.35) continue;
    if (why === 'greet' && Math.hypot(w.pos[0] - N.door_in[0], w.pos[1] - N.door_in[1]) > 420) continue;
    if (w.mode === 'seated' && w.place) {
      if (WORKING.has(w.stage) && why === 'greet') continue;
      w.shot(w.seatedClip('talk'), t);
    } else {
      w.shot(why === 'greet' ? 'wave' : pick(['celebrate', 'laugh', 'wave']), t);
    }
    if (why === 'success') w.sayLine(pick(LINES.cheer), t, 1.8);
  }
};
