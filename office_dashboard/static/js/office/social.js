'use strict';
/* Cosmetic office life. Never changes assignments, daemon work or learned memory. */
const social = {visits:new Map(), nextVisit:Date.now()+45000, nextTick:0, paused:storage.get('artel-motion-paused', false), freezeAt:0,
  reduced:window.matchMedia('(prefers-reduced-motion: reduce)')};
function officeMotionPaused() { return social.paused || social.reduced.matches; }
function updateMotionControl() {
  const paused = officeMotionPaused(), button = $('motionToggle');
  social.freezeAt = office.t;
  document.body.classList.toggle('motion-paused', paused);
  if (button) {
    button.textContent = social.reduced.matches ? tr("Движение сокращено", "Reduced motion") : paused ? tr("Включить анимацию", "Resume animation") : tr("Приостановить анимацию", "Pause animation");
    button.setAttribute('aria-pressed', String(paused));
    button.disabled = social.reduced.matches;
    button.title = social.reduced.matches ? tr("По настройке уменьшения движения в системе. Статусы и логи обновляются.", "Following your system reduced motion preference. Status and logs keep updating.") : tr("Останавливает только движение персонажей. Статусы и логи продолжат обновляться.", "Pauses character motion. Status and logs keep updating.");
  }
  if (paused) social.visits.clear();
  for (const w of office.workers.values()) w.stillKey = null;
  if (office.plate) { syncOffice(); renderBuilding(); renderCards(); }
}
$('motionToggle')?.addEventListener('click', () => {
  social.paused = !social.paused;
  storage.set('artel-motion-paused', social.paused);
  updateMotionControl();
});
social.reduced.addEventListener('change', updateMotionControl);
updateMotionControl();
function socialRoom(d) {
  const v=social.visits.get(d.id);
  return v && ['visiting','returning'].includes(v.phase) ? v.target : d.office_id;
}
function startOfficeVisit(id, target, requested=false) {
  if (officeMotionPaused()) return false;
  const d=lastSnapshot.daemons.find(d=>d.id===id);
  if(!d || d.alive===false || d.stage!=='idle' || social.visits.has(id) || target===d.office_id) return false;
  const hosts=lastSnapshot.daemons.filter(h=>h.office_id===target && h.alive!==false && h.stage==='idle');
  if(!hosts.length || [...social.visits.values()].some(v=>v.target===target)) return false;
  const w=office.workers.get(id);
  if(w && !w.free && !requested) return false;
  social.visits.set(id,{home:d.office_id,target,phase:'leaving',at:Date.now()});
  if(w) leaveForVisit(w,tr("Зайду к коллегам в другой офис", "Visiting colleagues in another office"));
  renderBuilding(); return true;
}
function leaveForVisit(w, text) {
  w.endPlan(office.t,true);
  w.startPlan('office-visit',[{place:w.placeFor('stopped'),dur:3600,say:text}],office.t);
}
function socialTick(now) {
  if(officeMotionPaused() || document.hidden || now<social.nextTick || !lastSnapshot?.daemons) return;
  social.nextTick=now+500;
  let changed=false;
  for(const [id,v] of social.visits) {
    const d=lastSnapshot.daemons.find(d=>d.id===id), w=document.body.classList.contains('view-stats') ? null : office.workers.get(id);
    if(!d || d.alive===false || d.stage!=='idle' || d.office_id!==v.home || !(lastSnapshot.offices||[]).some(r=>r.id===v.target)) {
      social.visits.delete(id); changed=true;continue;
    }
    if (w && ['leaving','returning'].includes(v.phase) && w.visible && w.plan?.kind !== 'office-visit') leaveForVisit(w,tr("До встречи!", "See you!"));
    if(v.phase==='leaving' && (!w || !w.visible)) {v.phase='visiting';v.at=now;changed=true;}
    else if(v.phase==='visiting' && now-v.at>45000) {
      v.phase='returning';v.at=now;
      if(w) leaveForVisit(w,tr("Спасибо за беседу! Возвращаюсь к себе", "Thanks for the chat! Heading back"));
      changed=true;
    } else if(v.phase==='returning' && (!w || !w.visible)) {social.visits.delete(id);changed=true;}
  }
  if(now>social.nextVisit) {
    social.nextVisit=now+60000+Math.random()*60000;
    const candidates=lastSnapshot.daemons.filter(d=>d.stage==='idle' && d.alive!==false && !social.visits.has(d.id));
    if(candidates.length>1) {
      const guest=pick(candidates), hosts=candidates.filter(d=>d.office_id!==guest.office_id);
      if(hosts.length) changed=startOfficeVisit(guest.id,pick(hosts).office_id)||changed;
    }
  }
  if(changed && office.plate) {syncOffice();renderBuilding();renderCards();}
}
function ownerReaction(id, kind) {
  const w=office.workers.get(id);
  if(!w || !w.visible || w.lost) return;
  w.feedback={kind,at:office.t};
  if (!officeMotionPaused()) w.shot(w.mode==='seated' ? w.seatedClip(kind==='praise'?'win':'talk') : kind==='praise'?'celebrate':'think',office.t);
  w.sayLine(kind==='praise'?tr("Спасибо! Звезда за работу ★", "Thanks! A star for my work ★"):tr("Замечание принято. Давай разберём результат.", "Feedback received. Let us review the result."),office.t,5);
  if(kind==='praise' && !officeMotionPaused()) office.react(w,office.t,'success');
}
function reactionOffset(w,t) {
  if(!w.feedback || officeMotionPaused()) return [0,0];
  const age=t-w.feedback.at;
  if(age<0 || age>3) return [0,0];
  const fade=Math.max(0,1-age/3);
  return w.feedback.kind==='praise' ? [0,-Math.abs(Math.sin(age*5))*8*fade] : [Math.sin(age*10)*3*fade,Math.sin(age*2)*2];
}
function drawReaction(w,g,t) {
  if(!w.feedback || office.t-w.feedback.at>5) return;
  const age=Math.max(0,office.t-w.feedback.at), praise=w.feedback.kind==='praise';
  g.save();g.globalAlpha=Math.min(1,(5-age)*2);g.textAlign='center';g.font='bold 22px system-ui';
  g.fillStyle=praise?'#ffd575':'#c4c9ff';
  g.fillText(praise?'★':'…',w.pos[0],w.headY()-22);
  if(praise && !officeMotionPaused()) {
    for(let i=0;i<10;i++) {const angle=i*Math.PI/5, radius=15+age*12;
      g.fillStyle=['#ffd575','#70dbc4','#e7a2bf'][i%3];
      g.fillRect(w.pos[0]+Math.cos(angle)*radius,w.headY()-25+Math.sin(angle)*radius+age*4,3,3);
    }
  }
  g.restore();
}
// Paired brainstorming and coffee exchanges use existing pathfinding and clips.
ACTIVITIES.brainstorm=(a,t,all)=>{
  const b=all.find(w=>w!==a&&w.free);if(!b||office.spots.has('brainstorm'))return false;
  office.spots.add('brainstorm');
  const duration=18;
  a.startPlan('brainstorm',[{place:standPlace('brainstorm',[N.board[0]-35,N.board[1]],'up','think','board'),dur:duration,
    onArrive:tt=>dialog(a,b,tt,[[tr("Проверим крайний случай?", "Shall we check the edge case?"),tr("Добавим его в тесты.", "Let us add a test for it.")],[tr("Как сделать проще?", "How can we simplify it?"),tr("Начнём с самого короткого сценария.", "Start with the shortest scenario.")]])}],t,{spot:'brainstorm'});
  b.startPlan('brainstorm',[{place:standPlace('brainstorm-b',[N.board[0]+10,N.board[1]+15],'up','think','board'),dur:duration}],t);
  return true;
};
ACTIVITY_WEIGHTS.brainstorm=2;
ACTIVITIES.coffeeExchange=(a,t,all)=>{
  const b=all.find(w=>w!==a&&w.free);if(!b)return false;
  const ok=ACTIVITIES.chat(a,t,all);
  if(ok) {a.sayLine(tr("Кому кофе после хорошего теста?", "Coffee after a good test?"),t,3);b.replies.push({at:t+5,text:tr("Мне! А потом посмотрим на результат.", "Yes! Then let us check the result."),pose:'coffee',dur:3});}
  return ok;
};
ACTIVITY_WEIGHTS.coffeeExchange=1.5;
