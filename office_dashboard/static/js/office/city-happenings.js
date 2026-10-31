'use strict';
/* Street happenings: a festival parade, a helicopter, a cat up a tree… One at a time, minutes apart,
   on the scene clock, so pausing the scene, a hidden tab or reduced motion stops them.
   They are pure decoration and never stand for daemon data; the caption names what is going on.
   Each happening may draw on the ground (under everything), add depth-sorted objects to the street,
   and draw in the air above the scene. cityHappen('parade', .5) starts one by hand. */
const cityHappenings = {current:null, next:null, last:null, label:''};
const cityHash = n => { const v=Math.sin(n*12.9898+78.233)*43758.5453; return v-Math.floor(v); };
const cityStep = (t,a,b) => Math.max(0,Math.min(1,(t-a)/(b-a)));
const citySmooth = x => x*x*(3-2*x);
const cityLerp = (a,b,f) => a.map((v,i) => v+(b[i]-v)*f);
const CITY_LANE = {east:308, west:374};

// A pedestrian in the same voxel style as the street walkers.
function cityPerson(k, x, y, shirt, {stride=0, arm=false, cone=false, bib=false, sit=0}={}) {
  const {box}=k;
  k.shadow(x-2,y-2,6,5,15);
  if(!sit) { box(x-2,y-1+stride,0,2,3,7,'#35474b');box(x+2,y-1-stride,0,2,3,7,'#35474b'); }
  box(x-3,y-2,7+sit,8,5,10,shirt,shirt,shirt);
  if(bib) box(x-1,y+3,10+sit,5,.2,4,'#ffffff','#ffffff','#ffffff');
  box(x-1,y-1,17+sit,5,4,5,'#d0ad8b','#a48e77','#655e50');
  if(arm) box(x+4,y,15+sit,2,2,9,shirt,shirt,shirt);
  if(cone) { const q=k.p(x+6,y+1,23+sit);k.tri([q[0]-2*k.s,q[1]],[q[0]+2*k.s,q[1]],[q[0],q[1]+6*k.s],'#d9a066');k.disc([q[0],q[1]-1*k.s],2.6*k.s,['#ffb3c7','#fff1c1','#a8e6cf','#c9a27e'][Math.floor(x)%4]); }
}
function cityWheels(k, x, lane, len) { for(const dx of [5,len-10])for(const dy of [0,16])k.box(x+dx,lane+dy,1,5,2,6,'#26383e','#1e3036','#3b4d51'); }
function cityNote(k, q, text, color, size=12) {
  const g=k.g;g.save();g.font=`700 ${Math.round(size*Math.max(.8,k.s))}px system-ui, sans-serif`;g.fillStyle=color;g.textAlign='center';g.fillText(text,q[0],q[1]);g.restore();
}
function cityBubble(k, q, text) {
  const g=k.g;g.save();g.font='600 11px system-ui, sans-serif';
  const tw=g.measureText?.(text)?.width||text.length*6.5, x=q[0]-tw/2-7, y=q[1]-22;
  g.beginPath();if(typeof g.roundRect==='function')g.roundRect(x,y,tw+14,18,9);else g.rect(x,y,tw+14,18);
  g.fillStyle=k.dark?'#1d242aee':'#ffffffee';g.fill();g.strokeStyle=k.dark?'#52616b':'#c5ced6';g.lineWidth=1;g.stroke();
  g.fillStyle=k.dark?'#e9eef1':'#18212b';g.textBaseline='middle';g.fillText(text,x+7,y+9.5);g.restore();
}
// A free patch of lawn that is on screen: off lots, paths, the street and trees, clear of the caption.
function cityLawnSpot(k, b, seed=0) {
  const lots=[...k.buildings.map(o=>[o.x-90,o.y-90,o.x+310,o.y+250]),
    ...k.scenery.map(s=>[s.x-60,s.y-60,s.x+s.w+60,s.y+s.d+(s.kind==='school'?150:60)])];
  const trees=typeof cityGrove==='function'?cityGrove(k.buildings,k.scenery):[];
  const spots=[];
  for(let x=b.x-700;x<=b.x+1000;x+=40)for(let y=-420;y<=860;y+=40) {
    if(y>150&&y<540)continue;
    if(lots.some(([l,t,r,bm])=>x>l-70&&x<r+70&&y>t-50&&y<bm+50))continue;
    if(trees.some(t=>Math.abs(t.x-x)<46&&Math.abs(t.y-y)<46))continue;
    const q=k.p(x,y,0);
    if(q[0]<k.w*.42||q[0]>k.w*.9||q[1]<k.h*.3||q[1]>k.h*.8)continue;
    spots.push({x,y,score:Math.hypot(q[0]-k.w*.66,q[1]-k.h*.55)});
  }
  spots.sort((a,c)=>a.score-c.score);
  const pick=spots[Math.floor(seed*Math.min(6,spots.length))]||spots[0];
  return pick?{x:pick.x,y:pick.y}:{x:b.x+430,y:-70};
}
function cityShopFor(k, b) {
  const shops=k.scenery.filter(s=>s.kind==='shop');
  return shops.sort((a,c)=>Math.abs(a.x-b.x-300)-Math.abs(c.x-b.x-300))[0]||null;
}

const CITY_HAPPENINGS = {
  parade: {
    dur:36, title:()=>tr('по улице едет фестиваль', 'a festival parade is passing by'),
    setup:k=>({b:k.anchor.number, from:k.anchor.x-760, to:k.anchor.x+980}),
    world(k) {
      const d=k.data, speed=(d.to-d.from+5*86)/this.dur, lane=CITY_LANE.east, wob=Math.sin(k.t*5);
      ['drums','duck','dragon','balloons','clown'].forEach((unit,i)=>{
        const x=d.from+speed*k.t-i*86;
        if(x<d.from-80||x>d.to||!k.visible(x-10,lane-10,70,40,90))return;
        k.add(x+lane+26,()=>{
          const {box,p,disc,s}=k;
          k.shadow(x,lane,48,18,14);
          if(unit==='drums') {
            box(x,lane,4,32,18,12,'#e4578c','#b8436f','#f27aa5');box(x+32,lane+1,4,13,16,14,'#f6c344','#c99b2b','#ffd76a');
            const q=p(x+15,lane+9,30+wob*1.5);disc(q,10*s,'#fff3e0');k.g.beginPath();k.g.arc(q[0],q[1],10*s,0,Math.PI*2);k.g.strokeStyle='#b8436f';k.g.lineWidth=2;k.g.stroke();
            for(let n=0;n<3;n++){const r=(k.t*.7+n/3)%1;k.g.globalAlpha=1-r;cityNote(k,p(x+12+n*6,lane+9,44+r*46),n%2?'♫':'♪','#b8436f',13);k.g.globalAlpha=1;}
          } else if(unit==='duck') {
            box(x,lane,4,42,18,6,'#5aa9e6','#3f85bd','#7cc0f0');
            const bob=wob*2, body=p(x+18,lane+9,24+bob), head=p(x+31,lane+9,40+bob);
            k.g.beginPath();k.g.ellipse(body[0],body[1],17*s,11*s,0,0,Math.PI*2);k.g.fillStyle='#ffd23f';k.g.fill();
            disc(head,8.5*s,'#ffd23f');k.tri([head[0]+6*s,head[1]-1*s],[head[0]+15*s,head[1]+1*s],[head[0]+6*s,head[1]+3*s],'#f08a24');disc([head[0]+3*s,head[1]-3*s],1.6*s,'#1d1d1d');
          } else if(unit==='dragon') {
            for(let j=0;j<5;j++){const z=6+Math.sin(k.t*6-j*.9)*5;box(x+j*9,lane+4,z,8,10,9,j%2?'#e94f37':'#f2a541',j%2?'#b83b2a':'#c98330',j%2?'#f06a55':'#f7bd6b');}
            const hz=8+Math.sin(k.t*6+.9)*5;box(x+45,lane+3,hz,12,12,12,'#e94f37','#b83b2a','#f06a55');
            const eye=p(x+52,lane+3,hz+9);disc(eye,2.2*s,'#ffffff');disc([eye[0]+.6*s,eye[1]],1*s,'#1d1d1d');
            k.line([x+57,lane+9,hz+4],[x+66,lane+2,hz+8],'#f2c14e',1.4);k.line([x+57,lane+9,hz+4],[x+66,lane+16,hz+8],'#f2c14e',1.4);
            for(let j=0;j<4;j++)k.person(x+4+j*11,lane+20,['#2a9d8f','#e76f51','#264653','#e9c46a'][j],{stride:Math.sin(k.t*8+j)*1.5});
          } else if(unit==='balloons') {
            box(x,lane,4,26,16,10,'#7bc67e','#5a9e5d','#9bd89d');
            for(let j=0;j<5;j++){const top=p(x+5+j*4,lane+8,58+j*5+Math.sin(k.t*2+j)*3), base=p(x+13,lane+8,14);
              k.g.beginPath();k.g.moveTo(...base);k.g.lineTo(...top);k.g.strokeStyle='#5f6b6d';k.g.lineWidth=.8;k.g.stroke();
              disc(top,6.5*s,['#ef476f','#ffd166','#06d6a0','#118ab2','#c77dff'][j]);disc([top[0]-2*s,top[1]-2*s],1.8*s,'#ffffff99');}
          } else {
            const hop=Math.abs(Math.sin(k.t*7))*4;
            box(x+4,lane+1,4+hop,22,15,9,'#9b5de5','#7a43bd','#b57ef0');
            for(const dx of [8,16])disc(p(x+dx,lane+16.2,9+hop),1.8*s,'#ffd166');
            box(x+12,lane+5,13+hop,5,5,5,'#ffe0c2','#e8c09e','#ff8fab');disc(p(x+17,lane+7,15+hop),1.8*s,'#e63946');
            for(const dx of [6,22])for(const dy of [0,15])box(x+dx,lane+dy,0,6,2,7,'#26383e','#1e3036','#3b4d51');
          }
          if(unit!=='clown') cityWheels(k,x,lane,unit==='drums'?44:unit==='dragon'?40:unit==='duck'?42:26);
        });
      });
    },
    sky(k) {
      const d=k.data, speed=(d.to-d.from+5*86)/this.dur, head=d.from+speed*k.t, colors=['#ef476f','#ffd166','#06d6a0','#118ab2','#f78c6b'];
      for(let i=0;i<46;i++) {
        const fall=(k.t*.55+cityHash(i))%1, x=head-cityHash(i+7)*5*86, q=k.p(x,CITY_LANE.east+(cityHash(i+3)-.5)*60,95-fall*90);
        if(q[0]<-10||q[0]>k.w+10)continue;
        k.g.save();k.g.translate(q[0],q[1]);k.g.rotate(k.t*4+i);k.g.fillStyle=colors[i%5];k.g.globalAlpha=1-fall*.6;k.g.fillRect(-1.5,-2.5,3,5);k.g.restore();
      }
    },
  },
  helicopter: {
    dur:28, title:k=>tr(`на крышу «${k.anchor.title}» садится вертолёт`, `a helicopter is landing on ${k.anchor.title}`),
    setup:k=>({b:k.anchor.number}),
    sky(k) {
      const b=k.building(k.data.b);if(!b)return;
      const roof=(56+b.floors*62+9)*CITY_HEIGHT, pad=[b.x+110,b.y+82,roof+1], T=k.t, {g,p,s}=k;
      const from=[b.x-560,b.y-420,roof+340], hover=[pad[0],pad[1],roof+120], away=[b.x+780,b.y-480,roof+380];
      let pos, spin=1;
      if(T<7) pos=cityLerp(from,hover,citySmooth(T/7));
      else if(T<10) pos=cityLerp(hover,[pad[0],pad[1],roof+6],citySmooth((T-7)/3));
      else if(T<21) { pos=[pad[0],pad[1],roof+6+Math.max(0,T-20)*24]; spin=T<13?1-(T-10)/3*.85:T<18?.15:.15+(T-18)/3*.85; }
      else pos=cityLerp([pad[0],pad[1],roof+30],away,citySmooth((T-21)/7));
      // Landing pad: painted on the roof for the visit.
      const q0=p(...pad), fade=Math.min(1,T/2,(this.dur-T)/2);
      g.globalAlpha=fade;g.beginPath();g.ellipse(q0[0],q0[1],21*s,10.5*s,0,0,Math.PI*2);g.fillStyle='#37474f';g.fill();g.strokeStyle='#f2c14e';g.lineWidth=1.6;g.stroke();
      cityNote(k,[q0[0],q0[1]+4*s],'H','#ffffff',11);g.globalAlpha=1;
      const over=Math.abs(pos[0]-pad[0])<140&&Math.abs(pos[1]-pad[1])<140, ground=p(pos[0],pos[1],over?roof+1:0), lift=Math.max(0,pos[2]-(over?roof:0));
      g.beginPath();g.ellipse(ground[0],ground[1],(18+lift*.05)*s,(7+lift*.02)*s,0,0,Math.PI*2);g.fillStyle=`rgba(10,25,30,${Math.max(.06,.28-lift*.0012)})`;g.fill();
      const q=p(...pos);g.save();g.translate(...q);
      g.strokeStyle='#c4442f';g.lineWidth=3.5*s;g.beginPath();g.moveTo(-6*s,-1*s);g.lineTo(-31*s,-6*s);g.stroke();
      k.tri([-31*s,-6*s],[-37*s,-15*s],[-27*s,-7*s],'#c4442f');
      g.globalAlpha=.4;g.beginPath();g.arc(-32*s,-6*s,4.5*s,0,Math.PI*2);g.fillStyle='#2b2f33';g.fill();g.globalAlpha=1;
      g.strokeStyle='#2b2f33';g.lineWidth=1.6*s;g.beginPath();g.moveTo(-13*s,11*s);g.lineTo(13*s,11*s);g.moveTo(-6*s,6*s);g.lineTo(-7*s,11*s);g.moveTo(6*s,6*s);g.lineTo(7*s,11*s);g.stroke();
      g.beginPath();g.ellipse(0,0,15*s,9*s,0,0,Math.PI*2);g.fillStyle='#e8553d';g.fill();
      g.beginPath();g.ellipse(7*s,-2*s,7*s,5.5*s,0,0,Math.PI*2);g.fillStyle='#a7d8e8';g.fill();
      g.fillStyle='#ffffff';g.fillRect(-11*s,1*s,12*s,2*s);
      g.beginPath();g.moveTo(0,-9*s);g.lineTo(0,-13*s);g.strokeStyle='#2b2f33';g.lineWidth=2*s;g.stroke();
      if(spin>.4) { g.globalAlpha=.13*spin;g.beginPath();g.ellipse(0,-13*s,31*s,13*s,0,0,Math.PI*2);g.fillStyle='#2b2f33';g.fill();g.globalAlpha=1; }
      const a=T*16*spin;g.lineWidth=2*s;g.beginPath();
      for(const off of [0,Math.PI/2]){const c=Math.cos(a+off),sn=Math.sin(a+off);g.moveTo(-c*31*s,-13*s-sn*13*s);g.lineTo(c*31*s,-13*s+sn*13*s);}
      g.stroke();g.restore();
    },
  },
  balloon: {
    dur:46, title:()=>tr('над кварталом пролетает воздушный шар', 'a hot-air balloon drifts overhead'),
    sky(k) {
      const {g}=k, s=Math.max(.75,Math.min(1.3,k.s)), r=27*s, fade=Math.min(1,k.t/3,(this.dur-k.t)/3);
      const q=[-60+(k.w+120)*k.f, k.h*(.2-.08*k.f)+Math.sin(k.t*.9)*5];
      g.globalAlpha=fade;
      g.strokeStyle='#6b5a45';g.lineWidth=1;g.beginPath();g.moveTo(q[0]-r*.55,q[1]+r*.75);g.lineTo(q[0]-5*s,q[1]+r*1.55);g.moveTo(q[0]+r*.55,q[1]+r*.75);g.lineTo(q[0]+5*s,q[1]+r*1.55);g.stroke();
      g.fillStyle='#8a6a43';g.fillRect(q[0]-6*s,q[1]+r*1.55,12*s,8*s);
      g.save();g.beginPath();g.arc(q[0],q[1],r,0,Math.PI*2);g.moveTo(q[0]-r*.75,q[1]+r*.65);g.lineTo(q[0],q[1]+r*1.3);g.lineTo(q[0]+r*.75,q[1]+r*.65);g.clip();
      ['#f4a259','#f7e8c6','#5b8e7d','#f7e8c6','#f4a259','#f7e8c6','#5b8e7d'].forEach((fill,i)=>{g.fillStyle=fill;g.fillRect(q[0]-r+i*(2*r/7),q[1]-r,2*r/7+1,r*2.4);});
      g.fillStyle='rgba(255,255,255,.18)';g.beginPath();g.arc(q[0]-r*.35,q[1]-r*.35,r*.45,0,Math.PI*2);g.fill();g.restore();
      if(Math.sin(k.t*3)>.4)k.disc([q[0],q[1]+r*1.35],3*s,'#ffb347');
      g.globalAlpha=1;
    },
  },
  icecream: {
    dur:32, title:()=>tr('приехал фургон с мороженым', 'the ice-cream van has arrived'),
    setup(k) {
      const shop=cityShopFor(k,k.anchor), north=!shop||shop.y<300;
      return {stop:shop?shop.x+shop.w/2:k.anchor.x+300, north};
    },
    world(k) {
      const d=k.data, T=k.t, dir=d.north?1:-1, lane=d.north?CITY_LANE.east:CITY_LANE.west, curb=d.north?266:418, wait=d.north?252:438;
      const x=T<8?d.stop-dir*720*(1-citySmooth(T/8)):T<23?d.stop:d.stop+dir*720*citySmooth((T-23)/9), music=T>8&&T<23;
      if(k.visible(x-10,lane,60,20,50)) k.add(x+lane+26,()=>{
        const {box,p,s}=k;
        k.shadow(x,lane,44,18,16);
        box(x,lane,4,34,18,17,'#fdf6ec','#e9dcc8','#ffd1df');box(x+(dir>0?34:-10),lane+1,4,10,16,12,'#f7a6c1','#d9849f','#ffc1d5');
        k.poly([[x+2,lane+18.2,10],[x+32,lane+18.2,10],[x+32,lane+18.2,13],[x+2,lane+18.2,13]],'#f7a6c1');
        const top=p(x+17,lane+9,28);k.tri([top[0]-6*s,top[1]],[top[0]+6*s,top[1]],[top[0],top[1]+12*s],'#d9a066');k.disc([top[0],top[1]-3*s],7*s,'#ffb3c7');k.disc([top[0]+2*s,top[1]-9*s],2.2*s,'#e63946');
        cityWheels(k,x,lane,44);
        if(music)for(let n=0;n<2;n++){const r=(T*.6+n/2)%1;k.g.globalAlpha=1-r;cityNote(k,p(x+20,lane+9,36+r*40),n?'♫':'♪','#d9849f');k.g.globalAlpha=1;}
      });
      // Customers walk to the kerb, wait for their cones and wander off.
      for(let i=0;i<4;i++) {
        const home=d.stop+(i-1.5)*46, spot=d.stop+(i-1.5)*10, come=citySmooth(cityStep(T,9+i*.6,13+i*.6)), go=citySmooth(cityStep(T,24,30));
        if(!come)continue;
        const px=home+(spot-home)*come*(1-go), py=wait+(curb-wait)*come*(1-go);
        if(go>=1||!k.visible(px-4,py-4,10,10,26))continue;
        k.add(px+py+2,()=>k.person(px,py,['#e76f51','#2a9d8f','#e9c46a','#8ab17d'][i],{stride:(come<1||go>0)?Math.sin(T*8+i)*1.6:0,cone:T>15+i*.5}));
      }
    },
  },
  marathon: {
    dur:30, title:()=>tr('по тротуару бежит городской забег', 'a city fun run is coming along the pavement'),
    setup:k=>({from:k.anchor.x-760, to:k.anchor.x+960}),
    world(k) {
      const d=k.data, speed=(d.to-d.from+260)/this.dur;
      for(let i=0;i<11;i++) {
        // The kerb-side strip of the pavement, clear of shop fronts.
        const x=d.from+speed*k.t-i*24-cityHash(i)*18, y=253+(i%3)*6;
        if(x<d.from-30||x>d.to||!k.visible(x-4,y-4,10,10,26))continue;
        k.add(x+y+2,()=>k.person(x,y,['#ef476f','#118ab2','#06d6a0','#ffd166','#8338ec','#fb5607'][i%6],{stride:Math.sin(k.t*13+i)*2.4,bib:true,arm:i===0}));
      }
    },
    sky(k) {
      const d=k.data, speed=(d.to-d.from+260)/this.dur, lead=k.p(d.from+speed*k.t,253,30);
      if(lead[0]>-20&&lead[0]<k.w+20&&k.t>2&&k.t<9)cityBubble(k,lead,tr('Последний круг!', 'Last lap!'));
    },
  },
  ufo: {
    dur:22, weight:.5, title:()=>tr('над лужайкой завис НЛО', 'a UFO is hovering over the lawn'),
    setup:k=>({spot:cityLawnSpot(k,k.anchor,cityHash(k.seed))}),
    sky(k) {
      const {spot}=k.data, T=k.t, {g,p,s}=k;
      const hover=[spot.x,spot.y,120], pos=T<4?cityLerp([spot.x-500,spot.y-300,420],hover,citySmooth(T/4)):T<15?[spot.x+Math.sin(T*1.3)*3,spot.y,120+Math.sin(T*2)*3]:cityLerp(hover,[spot.x+700,spot.y-700,700],citySmooth((T-15)/3));
      const beam=Math.min(cityStep(T,4,6),1-cityStep(T,13,14.5)), lift=citySmooth(cityStep(T,6.5,12.5)), ground=p(spot.x,spot.y,0), q=p(...pos);
      if(lift<1) {
        const gq=p(spot.x,spot.y,lift*110);g.globalAlpha=1-cityStep(lift,.85,1);
        k.disc([gq[0],gq[1]-4*s],3.4*s,'#3a6ea5');k.disc([gq[0],gq[1]-2*s],2.6*s,'#f1f1f1');
        k.tri([gq[0]-3.4*s,gq[1]-7*s],[gq[0]+3.4*s,gq[1]-7*s],[gq[0],gq[1]-16*s],'#d62828');k.disc([gq[0],gq[1]-8*s],1.6*s,'#f2c6a0');g.globalAlpha=1;
      }
      if(beam>0) {
        g.globalAlpha=beam*(k.dark?.42:.3);if(k.dark)g.globalCompositeOperation='lighter';
        g.beginPath();g.moveTo(q[0]-9*s,q[1]+4*s);g.lineTo(q[0]+9*s,q[1]+4*s);g.lineTo(ground[0]+24*s,ground[1]);g.lineTo(ground[0]-24*s,ground[1]);g.closePath();g.fillStyle='#b6f5e6';g.fill();
        g.beginPath();g.ellipse(ground[0],ground[1],24*s,10*s,0,0,Math.PI*2);g.fill();g.globalCompositeOperation='source-over';g.globalAlpha=1;
      }
      g.beginPath();g.ellipse(q[0],q[1]-4*s,10*s,8*s,0,Math.PI,0);g.fillStyle='#a7e8dc';g.fill();
      g.beginPath();g.ellipse(q[0],q[1],26*s,7*s,0,0,Math.PI*2);g.fillStyle='#8e9aa3';g.fill();
      g.beginPath();g.ellipse(q[0],q[1]+1.5*s,26*s,4*s,0,0,Math.PI);g.fillStyle='#66727a';g.fill();
      for(let i=0;i<6;i++){const a=i/6*Math.PI*2+T*3;if(Math.sin(a)<0)continue;k.disc([q[0]+Math.cos(a)*20*s,q[1]+Math.sin(a)*3.5*s],1.9*s,['#ffd166','#06d6a0','#ef476f'][i%3]);}
    },
  },
  firecat: {
    dur:34, title:()=>tr('пожарные снимают кота с дерева', 'firefighters are rescuing a cat from a tree'),
    setup(k) {
      const b=k.anchor, near=b.near;
      return {tree:{x:b.x-218,y:near?446:234}, lane:near?CITY_LANE.west:CITY_LANE.east, dir:near?-1:1};
    },
    truckX(k) { const d=k.data, T=k.t, stop=d.tree.x-20; return T<7?stop-d.dir*760*(1-citySmooth(T/7)):T<25?stop:stop+d.dir*760*citySmooth((T-25)/9); },
    world(k) {
      const d=k.data, x=this.truckX(k), lane=d.lane;
      if(!k.visible(x-10,lane,70,20,40))return;
      k.add(x+lane+26,()=>{
        const {box,p,s}=k;
        k.shadow(x,lane,52,18,16);
        box(x,lane,4,40,18,14,'#d64933','#a8382a','#e86a4f');box(x+(d.dir>0?40:-12),lane+1,4,12,16,15,'#d64933','#a8382a','#e86a4f');
        k.poly([[x+2,lane+18.2,9],[x+38,lane+18.2,9],[x+38,lane+18.2,11],[x+2,lane+18.2,11]],'#fdf0d5');
        box(x+6,lane+5,18,26,8,2,'#c0c6c8','#9aa1a3','#dfe4e6');
        const flash=Math.sin(k.t*9)>0;k.disc(p(x+(d.dir>0?46:-6),lane+9,21),2.6*s,flash?'#ffb703':'#fb8500');
        cityWheels(k,x,lane,52);
      });
    },
    sky(k) {
      const d=k.data, T=k.t, x=this.truckX(k), {g,p,s}=k;
      const base=p(x+18,d.lane+9,20), crown=p(d.tree.x,d.tree.y,48), reach=citySmooth(cityStep(T,7,11))*(1-citySmooth(cityStep(T,21,24)));
      if(reach>0) {
        const end=[base[0]+(crown[0]-base[0])*reach,base[1]+(crown[1]-base[1])*reach], nx=-(end[1]-base[1]), ny=end[0]-base[0], len=Math.hypot(nx,ny)||1, ox=nx/len*2.4*s, oy=ny/len*2.4*s;
        g.strokeStyle='#c0c6c8';g.lineWidth=1.4;g.beginPath();g.moveTo(base[0]+ox,base[1]+oy);g.lineTo(end[0]+ox,end[1]+oy);g.moveTo(base[0]-ox,base[1]-oy);g.lineTo(end[0]-ox,end[1]-oy);
        for(let r=.08;r<1;r+=.12){const mx=base[0]+(end[0]-base[0])*r,my=base[1]+(end[1]-base[1])*r;g.moveTo(mx+ox,my+oy);g.lineTo(mx-ox,my-oy);}g.stroke();
      }
      // The cat sits on the crown, walks down the ladder and rides away on the truck.
      const down=citySmooth(cityStep(T,11.5,19.5)), cat=T<11.5?[crown[0],crown[1]-8*s]:T<19.5?[crown[0]+(base[0]-crown[0])*down,crown[1]-8*s+(base[1]-crown[1]+4*s)*down]:[base[0],base[1]-4*s];
      g.beginPath();g.ellipse(cat[0],cat[1],5*s,3.4*s,0,0,Math.PI*2);g.fillStyle='#1f1f24';g.fill();
      k.disc([cat[0]+4.5*s,cat[1]-3*s],2.8*s,'#1f1f24');k.tri([cat[0]+2.6*s,cat[1]-5*s],[cat[0]+3.8*s,cat[1]-8.4*s],[cat[0]+4.8*s,cat[1]-5.4*s],'#1f1f24');k.tri([cat[0]+5*s,cat[1]-5.4*s],[cat[0]+6.6*s,cat[1]-8.4*s],[cat[0]+7*s,cat[1]-4.8*s],'#1f1f24');
      g.beginPath();g.moveTo(cat[0]-4.5*s,cat[1]);g.quadraticCurveTo(cat[0]-9*s,cat[1]-3*s+Math.sin(T*4)*2*s,cat[0]-7*s,cat[1]-8*s);g.strokeStyle='#1f1f24';g.lineWidth=1.6*s;g.stroke();
      if((T>1.5&&T<4)||(T>8&&T<10.5))cityBubble(k,[cat[0],cat[1]-6*s],tr('Мяу!', 'Meow!'));
      if(T>20&&T<23)cityBubble(k,[base[0],base[1]-10*s],tr('Спасён!', 'Rescued!'));
    },
  },
  birds: {
    dur:15, title:()=>tr('над кварталом пролетает стая птиц', 'a flock of birds flies over the district'),
    sky(k) {
      const lead=[k.w+60-(k.w+180)*k.f,k.h*.24-k.h*.1*k.f], {g}=k;
      g.strokeStyle=k.dark?'#c9d6dc':'#2f3e46';g.lineWidth=1.7;g.beginPath();
      for(let i=0;i<11;i++){
        const row=Math.ceil(i/2), side=i%2?1:-1, x=lead[0]+row*17, y=lead[1]+row*10*side, flap=Math.sin(k.t*11+i*.7)*4.5;
        g.moveTo(x-8,y-2+flap);g.quadraticCurveTo(x-3,y-6,x,y);g.quadraticCurveTo(x+3,y-6,x+8,y-2+flap);
      }
      g.stroke();
    },
  },
  rainbow: {
    dur:32, when:k=>!k.dark&&k.clear, title:()=>tr('над кварталом радуга', 'a rainbow over the district'),
    ground(k) {
      const {g}=k, fade=Math.sin(Math.PI*k.f), cx=k.w*.56, cy=k.h*1.04, r=Math.min(k.w*.42,k.h*.92);
      ['#ff595e','#ff924c','#ffca3a','#8ac926','#1982c4','#6a4c93'].forEach((c,i)=>{g.beginPath();g.arc(cx,cy,r-i*9,Math.PI,2*Math.PI);g.strokeStyle=c;g.globalAlpha=.3*fade;g.lineWidth=9;g.stroke();});
      g.globalAlpha=1;
    },
  },
  meteors: {
    dur:14, when:k=>k.dark, title:()=>tr('звездопад над кварталом', 'shooting stars over the district'),
    sky(k) {
      const {g}=k;g.globalCompositeOperation='lighter';
      for(let i=0;i<9;i++){
        const local=(k.t-i*1.35)/1.1;if(local<0||local>1)continue;
        const x0=k.w*(.3+cityHash(i+k.seed)*.7), y0=k.h*cityHash(i*3+k.seed)*.22, x=x0-220*local, y=y0+120*local;
        for(let j=0;j<4;j++){g.globalAlpha=(1-local)*(1-j/4);g.beginPath();g.moveTo(x+j*14,y-j*7.6);g.lineTo(x+(j+1)*14,y-(j+1)*7.6);g.strokeStyle='#fff6d5';g.lineWidth=2.2-j*.4;g.stroke();}
      }
      g.globalAlpha=1;g.globalCompositeOperation='source-over';
    },
  },
  drones: {
    dur:24, title:()=>tr('дроны развозят посылки', 'delivery drones are dropping off parcels'),
    setup(k) {
      const shop=cityShopFor(k,k.anchor)||{x:k.anchor.x+300,y:174,w:100,d:60,h:36};
      const houses=k.scenery.filter(s=>s.kind==='house').sort((a,b)=>Math.hypot(a.x-shop.x,a.y-shop.y)-Math.hypot(b.x-shop.x,b.y-shop.y)).slice(0,3);
      return {shop, houses};
    },
    sky(k) {
      const {shop,houses}=k.data, {g,p,s}=k;
      houses.forEach((house,i)=>{
        const go=citySmooth(cityStep(k.t,1+i*2,9+i*2)), up=citySmooth(cityStep(k.t,11+i*2,17+i*2));
        const from=[shop.x+shop.w/2,shop.y+shop.d/2,shop.h+12], roof=[house.x+house.w/2,house.y+house.d/2,house.h+26];
        const pos=up?cityLerp(roof,[roof[0]+260,roof[1]-260,roof[2]+260],up):[...cityLerp(from,roof,go).slice(0,2),from[2]+(roof[2]-from[2])*go+Math.sin(go*Math.PI)*70];
        if(go>=1){const box=p(roof[0],roof[1],house.h+30);g.fillStyle='#b5835a';g.fillRect(box[0]-4*s,box[1]-4*s,8*s,7*s);}
        if(up>=1)return;
        const q=p(...pos);g.globalAlpha=1-up;
        if(go<1){g.strokeStyle='#5f6b6d';g.lineWidth=.8;g.beginPath();g.moveTo(q[0],q[1]+2*s);g.lineTo(q[0],q[1]+8*s);g.stroke();g.fillStyle='#b5835a';g.fillRect(q[0]-4*s,q[1]+8*s,8*s,7*s);}
        g.fillStyle='#2f3e46';g.fillRect(q[0]-6*s,q[1]-1.5*s,12*s,3.5*s);
        for(const dx of [-8,8]){g.beginPath();g.ellipse(q[0]+dx*s,q[1]-3*s,6*s,1.8*s,0,0,Math.PI*2);g.fillStyle='rgba(47,62,70,.35)';g.fill();}
        k.disc([q[0],q[1]-1*s],1.4*s,Math.sin(k.t*10+i)>0?'#06d6a0':'#ef476f');g.globalAlpha=1;
      });
    },
  },
  kite: {
    dur:32, title:()=>tr('кто-то запускает воздушного змея', 'someone is flying a kite'),
    setup:k=>({spot:cityLawnSpot(k,k.anchor,cityHash(k.seed+3))}),
    world(k) {
      const {spot}=k.data;if(!k.visible(spot.x-6,spot.y-6,12,12,26))return;
      k.add(spot.x+spot.y+2,()=>k.person(spot.x,spot.y,'#3a86ff',{arm:true,stride:k.t<3?Math.sin(k.t*8)*1.6:0}));
    },
    sky(k) {
      const {spot}=k.data, {g,p,s}=k, rise=citySmooth(cityStep(k.t,0,6))*(1-citySmooth(cityStep(k.t,28,32)));
      const hand=p(spot.x+5,spot.y+1,25), kq=p(spot.x+90+Math.sin(k.t*.7)*14,spot.y-70,30+170*rise+Math.sin(k.t*1.3)*8);
      g.strokeStyle=k.dark?'#c9d6dc':'#4b5a60';g.lineWidth=.8;g.beginPath();g.moveTo(...hand);g.quadraticCurveTo((hand[0]+kq[0])/2,(hand[1]+kq[1])/2+30*s,kq[0],kq[1]);g.stroke();
      const r=11*s, tilt=Math.sin(k.t*1.1)*.25;g.save();g.translate(...kq);g.rotate(tilt);
      k.tri([0,-r*1.3],[r,0],[0,r*1.5],'#ef476f');k.tri([0,-r*1.3],[-r,0],[0,r*1.5],'#ffd166');
      g.strokeStyle='#2f3e46';g.lineWidth=.8;g.beginPath();g.moveTo(0,r*1.5);for(let i=1;i<7;i++)g.lineTo(Math.sin(k.t*4+i)*4*s,r*1.5+i*6*s);g.stroke();
      for(let i=2;i<7;i+=2)k.disc([Math.sin(k.t*4+i)*4*s,r*1.5+i*6*s],1.8*s,['#06d6a0','#118ab2','#ef476f'][i%3]);
      g.restore();
    },
  },
  dogs: {
    dur:32, title:()=>tr('выгул собак: пятеро на одном поводке', 'a dog walker with five dogs on leads'),
    setup:k=>({from:k.anchor.x-560, to:k.anchor.x+760}),
    world(k) {
      const d=k.data, x=d.from+(d.to-d.from)*k.f, y=446, colors=[['#8d6e4c','#6f553a'],['#f1f1f1','#d4d4d4'],['#2b2b2b','#1a1a1a'],['#d9a441','#b5862f'],['#c9774b','#a65f39']];
      if(!k.visible(x-10,y-30,90,60,26))return;
      k.add(x+y+2,()=>k.person(x,y,'#6a994e',{stride:Math.sin(k.t*7)*1.6,arm:true}));
      colors.forEach(([coat,side],i)=>{
        const dx=x+26+i*6+Math.sin(k.t*3+i)*3, dy=y-16+i*8+Math.sin(k.t*2+i*2)*2, hop=Math.abs(Math.sin(k.t*10+i))*1.5, small=i%2?.8:1;
        k.add(dx+dy+1,()=>{
          const {box,p}=k, hand=p(x+5,y+1,22), collar=p(dx+9*small,dy+2,6*small+hop);
          k.g.beginPath();k.g.moveTo(...hand);k.g.lineTo(...collar);k.g.strokeStyle='#7a2e2e';k.g.lineWidth=.8;k.g.stroke();
          k.shadow(dx,dy,10*small,5,6);box(dx,dy,2+hop,10*small,5,5*small,coat,side,coat);box(dx+8*small,dy,5*small+hop,4,5,4,coat,side,coat);
          box(dx+1,dy,0,1.5,5,2+hop,side,side,side);box(dx+7*small,dy,0,1.5,5,2+hop,side,side,side);
          k.line([dx,dy+2.5,6*small+hop],[dx-3,dy+2.5,9*small+hop+Math.sin(k.t*14+i)*1.5],side,1.4);
        });
      });
    },
  },
  ducks: {
    dur:20, title:()=>tr('утка с утятами переходит дорогу', 'a duck and her ducklings are crossing the road'),
    setup:k=>({x:k.anchor.x+102}),
    world(k) {
      const d=k.data;
      for(let i=0;i<6;i++){
        const y=258+(424-258)*cityStep(k.t,2+i*.7,15+i*.7), x=d.x+Math.sin(k.t*6+i)*1.5;
        if(k.t<2+i*.7||k.t>19||!k.visible(x-4,y-4,10,10,14))continue;
        k.add(x+y+1,()=>{
          const mom=i===0, r=(mom?7:4.2)*k.s, body=k.p(x,y,mom?6:4), head=k.p(x+(mom?5:3),y+1,mom?14:9), waddle=Math.sin(k.t*10+i)*.15;
          k.g.beginPath();k.g.ellipse(body[0],body[1]+2*k.s,r*1.1,r*.5,0,0,Math.PI*2);k.g.fillStyle='rgba(10,25,30,.15)';k.g.fill();
          k.g.beginPath();k.g.ellipse(body[0],body[1],r*1.25,r,waddle,0,Math.PI*2);k.g.fillStyle=mom?'#9c7a54':'#ffd23f';k.g.fill();
          k.disc(head,r*.62,mom?'#2d6a4f':'#ffd23f');k.tri([head[0]+r*.5,head[1]],[head[0]+r*1.15,head[1]+r*.2],[head[0]+r*.5,head[1]+r*.35],'#f08a24');
        });
      }
    },
    sky(k) {
      const d=k.data, y=258+(424-258)*cityStep(k.t,2,15);
      if((k.t>3&&k.t<5.5)||(k.t>10&&k.t<12.5))cityBubble(k,k.p(d.x,y,14),tr('Кря!', 'Quack!'));
    },
  },
  blimp: {
    dur:42, title:()=>tr('над кварталом плывёт дирижабль', 'an airship is floating overhead'),
    sky(k) {
      const {g}=k, s=Math.max(.75,Math.min(1.25,k.s)), fade=Math.min(1,k.t/3,(this.dur-k.t)/3);
      const q=[-120+(k.w+300)*k.f, k.h*(.12+.04*k.f)+Math.sin(k.t*.8)*4];
      g.globalAlpha=fade;
      const trail=[q[0]-150*s,q[1]+6*s];g.strokeStyle='#6b7a80';g.lineWidth=.8;g.beginPath();g.moveTo(q[0]-58*s,q[1]+4*s);g.lineTo(trail[0]+92*s,trail[1]);g.stroke();
      g.save();g.translate(trail[0],trail[1]);g.transform(1,Math.sin(k.t*2)*.04,0,1,0,0);
      g.fillStyle=k.dark?'#2f3e46':'#ffffff';g.fillRect(0,-9*s,92*s,18*s);g.strokeStyle=k.dark?'#83e3ce':'#087d70';g.lineWidth=1;g.strokeRect(0,-9*s,92*s,18*s);
      g.font=`700 ${Math.round(8.5*s)}px system-ui, sans-serif`;g.fillStyle=k.dark?'#83e3ce':'#087d70';g.textAlign='center';g.textBaseline='middle';g.fillText(tr('ТЕСТЫ ЗЕЛЁНЫЕ', 'ALL TESTS GREEN'),46*s,.5*s);g.restore();
      k.tri([q[0]-48*s,q[1]-6*s],[q[0]-66*s,q[1]-20*s],[q[0]-60*s,q[1]-2*s],'#9aa8ae');k.tri([q[0]-48*s,q[1]+6*s],[q[0]-66*s,q[1]+18*s],[q[0]-60*s,q[1]+2*s],'#9aa8ae');
      g.beginPath();g.ellipse(q[0],q[1],60*s,19*s,0,0,Math.PI*2);g.fillStyle=k.dark?'#c9d3d8':'#eef2f3';g.fill();g.strokeStyle='#9aa8ae';g.lineWidth=1;g.stroke();
      g.beginPath();g.ellipse(q[0]+8*s,q[1]-7*s,40*s,6*s,0,0,Math.PI*2);g.fillStyle='rgba(255,255,255,.5)';g.fill();
      g.fillStyle='#5a666b';g.fillRect(q[0]-10*s,q[1]+17*s,22*s,6*s);
      g.font=`800 ${Math.round(11*s)}px system-ui, sans-serif`;g.fillStyle='#087d70';g.textAlign='center';g.textBaseline='middle';g.fillText(tr('АРТЕЛЬ', 'ARTEL'),q[0]-2*s,q[1]+2*s);
      g.textAlign='start';g.textBaseline='alphabetic';g.globalAlpha=1;
    },
  },
  mower: {
    dur:34, title:()=>tr('газонокосилка подстригает лужайку', 'a mower is trimming the lawn'),
    setup:k=>({spot:cityLawnSpot(k,k.anchor,cityHash(k.seed+5))}),
    path(k) {
      // Boustrophedon over a 132 × 72 patch: four rows of stripes.
      const {spot}=k.data, rows=4, len=132, total=rows*len, done=Math.min(total,total*cityStep(k.t,2,30)), row=Math.min(rows-1,Math.floor(done/len)), along=done-row*len;
      const x=spot.x-66+(row%2?len-along:along), y=spot.y-36+row*18;
      return {rows,len,done,row,along,x,y,dir:row%2?-1:1};
    },
    ground(k) {
      const {spot}=k.data, m=this.path(k), fade=1-cityStep(k.t,30,34);
      k.g.globalAlpha=fade;
      for(let r=0;r<=m.row;r++){const full=r<m.row, w=full?m.len:m.along, x0=r%2?spot.x-66+m.len-w:spot.x-66;k.flat(x0,spot.y-36+r*18,w,17,-2.7,r%2?(k.dark?'#284a40':'#e3efdc'):(k.dark?'#22423a':'#d9e9d2'));}
      k.g.globalAlpha=1;
    },
    world(k) {
      const m=this.path(k);if(k.t>30.5||!k.visible(m.x-12,m.y-6,24,20,26))return;
      k.add(m.x+m.y+2,()=>{
        const {box}=k, x=m.x-(m.dir>0?16:0), y=m.y;
        k.shadow(x,y,18,12,10);box(x,y,2,18,12,7,'#d62828','#a81f1f','#ef4444');box(x+(m.dir>0?0:12),y+2,9,6,8,3,'#2b2f33','#1e2124','#3b4045');
        k.person(x+9,y+6,'#f4a261',{sit:3});
        for(const dx of [2,13])for(const dy of [0,11])box(x+dx,y+dy,0,3,1.5,4,'#26383e','#1e3036','#3b4d51');
      });
    },
  },
};

function cityHappen(id, progress=0) {
  if(!CITY_HAPPENINGS[id])return false;
  cityHappenings.current={id, start:city.time-Math.max(0,Math.min(.99,progress))*CITY_HAPPENINGS[id].dur, data:null, seed:Math.random()*1000};
  city.dirty=true;
  return true;
}
// Picks, advances and draws the current happening. Returns the air layer to draw after the street.
function cityHappeningFrame(kit) {
  const state=cityHappenings, now=city.time;
  if(state.next===null)state.next=now+45+Math.random()*45;
  const base={...kit, s:kit.c.scale, building:n=>kit.buildings.find(b=>b.number===n),
    tri:(a,b,c,fill)=>{kit.g.beginPath();kit.g.moveTo(...a);kit.g.lineTo(...b);kit.g.lineTo(...c);kit.g.closePath();kit.g.fillStyle=fill;kit.g.fill();}};
  base.person=(...args)=>cityPerson(base,...args);
  if(!state.current&&now>=state.next) {
    const eligible=Object.entries(CITY_HAPPENINGS).filter(([id,h])=>id!==state.last&&(!h.when||h.when(base)));
    let roll=Math.random()*eligible.reduce((n,[,h])=>n+(h.weight||1),0);
    const pick=eligible.find(([,h])=>(roll-=h.weight||1)<0)||eligible[0];
    if(pick)state.current={id:pick[0], start:now, data:null, seed:Math.random()*1000};
  }
  const current=state.current, h=current&&CITY_HAPPENINGS[current.id];
  if(!h)return null;
  const t=now-current.start;
  if(t>=h.dur) {
    state.last=current.id;state.current=null;state.next=now+150+Math.random()*210;
    return null;
  }
  const anchor=base.buildings.find(b=>b.number===city.focus)||base.buildings[Math.floor(cityHash(current.seed)*base.buildings.length)]||base.buildings[0];
  const k={...base, t:Math.max(0,t), f:Math.max(0,t)/h.dur, seed:current.seed, anchor};
  if(!current.data)current.data=h.setup?h.setup(k):{};
  k.data=current.data;
  h.ground?.(k);
  h.world?.(k);
  return {id:current.id, title:h.title(k), sky:()=>h.sky?.(k)};
}
