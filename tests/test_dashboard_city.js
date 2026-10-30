'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=['city-model.js','city-controls.js','city.js'].map(name=>fs.readFileSync(path.join(__dirname,'../office_dashboard/static/js/office',name),'utf8')).join('\n');
function harness(width=1200,height=600) {
  const elements={}, draws=[], opened=[], writes=[],requests=[],applied=[];
  let clock=1000,fetchReply=()=>{throw new Error('Unexpected fetch in city test');};
  const context2d=new Proxy({}, {get(obj,key){
    if(key==='createLinearGradient')return()=>({addColorStop(){}});
    if(key in obj)return obj[key];
    return (...args)=>{for(const v of args)if(typeof v==='number')assert(Number.isFinite(v),`${key}: non-finite coordinate`);draws.push([key,...args]);};
  },set(obj,key,value){obj[key]=value;return true;}});
  function element(id) {
    const classes=new Set();
    return {id,dataset:{},style:{},hidden:false,disabled:false,value:'',textContent:'',_html:'',buttons:[],options:[],listeners:{},listenerOptions:{},captures:new Set(),scrollTop:0,offsetTop:88,offsetLeft:width-364,clientHeight:420,
      classList:{add(...names){names.forEach(n=>classes.add(n));},remove(...names){names.forEach(n=>classes.delete(n));},contains:name=>classes.has(name)},
      get innerHTML(){return this._html;},set innerHTML(value){this._html=value;this.buttons=[...value.matchAll(/<button[^>]*data-city-(floor|action|building)="([^"]+)"/g)].map(m=>({...element('button'),dataset:{[{floor:'cityFloor',action:'cityAction',building:'cityBuilding'}[m[1]]]:m[2]}}));this.options=[...value.matchAll(/<option value="([^"]+)"/g)].map(m=>({value:m[1]}));if(this.options.length&&!this.options.some(o=>o.value===this.value))this.value=this.options[0].value;},
      addEventListener(type,fn,options){this.listeners[type]=fn;this.listenerOptions[type]=options;},setAttribute(key,value){this[key]=value;},
      contains(el){return this.buttons.includes(el);},querySelectorAll(){return this.buttons;},
      closest(selector){const key=selector.match(/\[data-city-(building|floor|action)\]/)?.[1];return key&&this.dataset[{building:'cityBuilding',floor:'cityFloor',action:'cityAction'}[key]]!==undefined?this:null;},
      querySelector(selector){const action=selector.match(/data-city-action="(.*?)"/)?.[1];return this.buttons.find(b=>b.dataset.cityAction===action);},
      setPointerCapture(id){this.captures.add(id);},hasPointerCapture(id){return this.captures.has(id);},releasePointerCapture(id){this.captures.delete(id);},
      focus(){document.activeElement=this;},select(){this.selectionStart=0;this.selectionEnd=this.value.length;},getBoundingClientRect(){return {width,height,left:0,top:0};},getContext(){return context2d;},
    };
  }
  const document={activeElement:null,documentElement:{dataset:{theme:'light'}},hidden:false};
  for(const id of ['cityCanvas','cityViewport','cityZoomIn','cityZoomOut','cityZoomValue','cityReset','cityFloors','cityPreview','cityStage','cityHint','cityBuildings','cityLabels','cityDistrictSummary','cityMotion','building','officeDirectory','buildingRooms','cityRenameOpen','cityNameBuilding','cityNameInput','cityNameStatus','cityNameForm','cityNameSave','cityNameCancel'])elements[id]=element(id);
  elements.cityNameForm.hidden=true;
  const env={document,window:{devicePixelRatio:2,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}},performance:{now:()=>clock},console,
    $:id=>elements[id],ResizeObserver:class {constructor(fn){this.fn=fn;}observe(){this.fn();}},IntersectionObserver:class {constructor(fn){this.fn=fn;}observe(){this.fn([{isIntersecting:true}]);}},requestAnimationFrame(){},
    esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    rosterFilter:{query:'',status:'all'},lastSnapshot:{daemons:[]},matchesDemon:d=>d.match!==false,
    roomStats:ds=>({bad:ds.filter(d=>d.stage==='error').length,busy:ds.filter(d=>d.stage==='generating').length}),
    office:{plate:{src:'/assets/office.png'}},appearanceThumb:()=>'/assets/character.png',SEATS:[{pos:[176,584]}],PLATE:1254,
    social:{paused:false,reduced:{matches:false}},storage:{set:(...args)=>writes.push(args)},updateMotionControl(){},
    openOffice:id=>opened.push(id),
    fetch:async(url,options)=>{requests.push({url,...options});return fetchReply(url,options);},
    apply:snap=>{applied.push(snap);env.lastSnapshot=snap;env.renderCityRooms(snap.offices||[]);},
  };
  env.officeMotionPaused=()=>env.social.paused||env.social.reduced.matches;
  vm.createContext(env);vm.runInContext(source,env);
  return {env,elements,document,draws,opened,writes,requests,applied,setFetch:fn=>fetchReply=fn,run:s=>vm.runInContext(s,env),clock:n=>clock=n};
}
const rooms=[{id:'api',title:'Сервисы',building_level:2,capacity:12},{id:'web',title:'Клиент',building_level:7,capacity:12}];
function catalogue(count) {return Array.from({length:count},(_,i)=>({id:`office-${i+1}`,title:'Команда',capacity:12,building_level:i+1}));}
function pointer(h,type,{id=1,x=200,y=220,pointerType='mouse',button=0,target=h.elements.cityCanvas}={}) {
  const event={type,pointerId:id,clientX:x,clientY:y,pointerType,button,target,preventDefault(){this.defaultPrevented=true;}};
  // Canvas handlers run before the viewport's bubbling handler, as in the browser.
  h.elements.cityCanvas.listeners[type]?.(event);
  h.elements.cityViewport.listeners[type]?.(event);
  return event;
}
function faceCenter(face) {return face.points.reduce((p,q)=>[p[0]+q[0]/4,p[1]+q[1]/4],[0,0]);}
function near(actual,expected,message,tolerance=1e-6) {assert(Math.abs(actual-expected)<tolerance,`${message}: ${actual} != ${expected}`);}
function viewValues(h) {return JSON.parse(h.run('JSON.stringify(city.view)'));}
function polygonsOverlap(a,b,epsilon=1e-6) {
  // Separating-axis test: edge contact is allowed; a positive-area intersection is not.
  for(const polygon of [a,b])for(let i=0;i<polygon.length;i++) {
    const p=polygon[i],q=polygon[(i+1)%polygon.length],axis=[p[1]-q[1],q[0]-p[0]],length=Math.hypot(...axis);
    if(!length)continue;
    const project=points=>points.map(v=>(v[0]*axis[0]+v[1]*axis[1])/length),pa=project(a),pb=project(b);
    if(Math.min(Math.max(...pa),Math.max(...pb))-Math.max(Math.min(...pa),Math.min(...pb))<=epsilon)return false;
  }
  return true;
}
function scenerySurfaces(s) {
  // Include protruding roofs, awnings and the school entrance, not just a bounding box.
  const {x,y,w,d,h}=s;
  const box=(bx,by,bw,bd,bh)=>[
    [[bx,by+bd,0],[bx+bw,by+bd,0],[bx+bw,by+bd,bh],[bx,by+bd,bh]],
    [[bx+bw,by,0],[bx+bw,by+bd,0],[bx+bw,by+bd,bh],[bx+bw,by,bh]],
    [[bx,by,bh],[bx+bw,by,bh],[bx+bw,by+bd,bh],[bx,by+bd,bh]],
  ];
  const surfaces=box(x,y,w,d,h);
  if(s.kind==='house')surfaces.push(
    [[x-5,y+d+5,h],[x+w/2,y+d+5,h+24],[x+w+5,y+d+5,h]],
    [[x+w/2,y-4,h+24],[x+w/2,y+d+5,h+24],[x+w+5,y+d+5,h],[x+w+5,y-4,h]],
  );
  if(s.kind==='shop')surfaces.push([[x,y+d,30],[x+w,y+d,30],[x+w,y+d+14,24],[x,y+d+14,24]]);
  if(s.kind==='school')surfaces.push(...box(x+w/2-21,y+d,42,12,48),
    [[x+w/2-30,y+d+13,48],[x+w/2,y+d+13,72],[x+w/2+30,y+d+13,48]]);
  return surfaces;
}
function rectsOverlap(a,b) {return a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y;}
test('16 offices per building; 17th and 33rd start new buildings on alternating street sides',()=>{
  const h=harness();
  for(const count of [0,1,15,16,17,32,33,64,65,160]) {
    const fixture=catalogue(count), buildings=h.env.cityLayout(fixture);
    assert.equal(buildings.length,Math.ceil(count/16));
    assert.equal(buildings.reduce((n,b)=>n+b.rooms.length,0),count);
    for(const b of buildings) {
      assert(b.rooms.length<=16);assert(b.floors<=16);
      assert.equal(b.near,b.number%2===0);assert(b.near?b.y>408:b.y+120<280);
      assert.equal(new Set(b.rooms.map(r=>r.floor)).size,b.rooms.length);
    }
  }
  assert.equal(h.env.cityAddress({building_level:17}).building,2);
  assert.equal(h.env.cityAddress({building_level:17}).floor,1);
});
test('addresses and world positions survive ordering, renaming, missing offices and growth',()=>{
  const h=harness(), before=h.env.cityLayout(catalogue(33));
  const after=h.env.cityLayout(catalogue(40).filter(r=>![3,9,18].includes(r.building_level)).reverse().map(r=>({...r,title:'Новое имя'})));
  for(const b of before) {
    const next=after.find(n=>n.number===b.number);assert.equal(next.x,b.x);assert.equal(next.y,b.y);
    for(const entry of b.rooms) {
      const current=next.rooms.find(e=>e.room.id===entry.room.id);
      if(current)assert.equal(current.floor,entry.floor);
    }
  }
});
test('city grows its people, traffic, houses, shops and schools with office buildings',()=>{
  const h=harness();let previous=null;
  for(const count of [1,2,3,5,9]) {
    const b=h.env.cityLayout(catalogue(count*16)), p=h.env.cityPopulation(count), scenery=h.env.citySurroundings(b);
    for(const [key,kind] of [['houses','house'],['shops','shop'],['schools','school']])assert.equal(scenery.filter(s=>s.kind===kind).length,p[key]);
    if(previous)for(const key of ['cars','people','houses','shops'])assert(p[key]>previous[key]);
    previous=p;
    let people=0,cars=0;
    for(let t=0;t<100;t++) {
      const actors=h.env.cityActors(b,t);people+=actors.people.length;cars+=actors.cars.length;
      for(const car of actors.cars)assert([308,374].includes(car.y));
      for(const person of actors.people)assert(b.some(building=>building.number===person.target));
    }
    assert(people>0&&cars>0);
  }
  const b=h.env.cityLayout(catalogue(17)), entering=h.env.cityActors(b,20.9).people;
  assert(entering.some(p=>p.target===1&&p.y<135));
  const other=h.env.cityActors(b,8.2).people;assert(other.some(p=>p.target===2&&p.y>500));
});
test('facades fit the overview and picking shares geometry on desktop/mobile, including multiple buildings',()=>{
  for(const width of [280,390,840,900,1200])for(const count of [0,1,16,17,33,65]) {
    const h=harness(width,width<=840?420:600);h.env.fixture=catalogue(count);
    h.run('renderCityRooms(fixture);drawCity()');
    const faces=h.run('city.faces');assert.equal(faces.length,count*2);
    const area=h.run('cityBaseCamera().area');
    for(const face of faces) {
      const center=face.points.reduce((p,q)=>[p[0]+q[0]/4,p[1]+q[1]/4],[0,0]);
      assert(center[0]>=area.left&&center[0]<=area.right);assert(center[1]>=area.top&&center[1]<=area.bottom);
      assert.equal(h.env.cityPick({clientX:center[0],clientY:center[1]}),face.id);
    }
    h.document.documentElement.dataset.theme='dark';h.run("city.theme='dark';drawCity()");
  }
});
test('foreground houses, shops and schools never cover a selectable office facade',()=>{
  const sparse=catalogue(129).filter(r=>[1,64,129].includes(r.building_level));
  for(const fixture of [...[1,16,17,32,33,49,65,160].map(catalogue),sparse]) {
    const h=harness();h.env.fixture=fixture;h.run('renderCityRooms(fixture);drawCity()');
    const buildings=h.run('city.buildings'),scenery=h.run('city.scenery'),faces=h.run('city.faces');
    const camera=h.env.cityCamera(1200,600,buildings,scenery);
    const byRoom=new Map(buildings.flatMap(b=>b.rooms.map(({room})=>[room.id,b])));
    for(const s of scenery) {
      const surfaces=scenerySurfaces(s).map(poly=>poly.map(p=>camera.project(...p)));
      for(const face of faces) {
        const b=byRoom.get(face.id);
        if(s.x+s.y+s.d<b.x+b.y+220)continue;
        assert(!surfaces.some(p=>polygonsOverlap(p,face.points)),
          `${fixture.length} offices: ${s.kind} at (${s.x},${s.y}) covers ${face.id}`);
      }
    }
  }
});
test('full building labels stay within the scene and never overlap at any supported overview scale',()=>{
  const h=harness(),sparse=catalogue(129).filter(r=>[1,64,129].includes(r.building_level));
  for(const fixture of [...[1,17,32,33,49,65,160].map(catalogue),sparse]) {
    const buildings=h.env.cityLayout(fixture),scenery=h.env.citySurroundings(buildings);
    for(const width of [280,390,840,900,1200])for(const focus of [null,...buildings.filter(b=>b.near).map(b=>b.number)]) {
      const height=width<=840?420:600,camera=h.env.cityCamera(width,height,buildings,scenery,focus);
      const labels=h.env.cityLabels(camera,buildings,focus),expected=focus===null?buildings:buildings.filter(b=>b.number===focus),area=camera.labelArea;
      assert.deepEqual([...labels].map(l=>l.number),[...expected].map(b=>b.number));
      for(const [i,label] of labels.entries()) {
        const context=`${fixture.length} offices, width ${width}, focus ${focus}, building ${label.number}`;
        assert.equal(label.text,`Корпус ${label.number}`,context);
        for(const n of [label.x,label.y,label.w,label.h,...label.anchor])assert(Number.isFinite(n),context);
        assert(label.x>=area.left&&label.x+label.w<=area.right+1e-6,context);
        assert(label.y>=area.top&&label.y+label.h<=area.bottom+1e-6,context);
        assert(label.h>=32&&label.w>=88,`${context}: must retain a readable click target`);
        for(const previous of labels.slice(0,i))assert(!rectsOverlap(label,previous),`${context}: overlaps building ${previous.number}`);
      }
    }
  }
});
test('scene labels are native full-text controls and retain keyboard focus after zoom and updates',()=>{
  const h=harness(390,420);h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);drawCity()');
  const labels=h.elements.cityLabels;
  assert.match(labels.innerHTML,/<button type="button"[^>]*data-city-building="2"[^>]*>Корпус 2<\/button>/);
  assert.match(labels.innerHTML,/aria-label="Приблизить корпус 2: Корпус 2"/);
  const button=labels.buttons.find(b=>b.dataset.cityBuilding==='2');button.focus();
  const initial=h.run('JSON.stringify(city.rooms)');
  labels.listeners.click({detail:0,target:{closest:()=>button}});h.run('drawCity()');
  assert.equal(h.run('city.focus'),2);assert.equal(h.document.activeElement.dataset.cityBuilding,'2');
  assert(labels.contains(h.document.activeElement));assert.equal(labels.buttons.length,1);
  assert.equal(h.run('JSON.stringify(city.rooms)'),initial,'zoom must not mutate office addresses or names');
  h.env.fixture=catalogue(18);h.run('renderCityRooms(fixture);drawCity()');
  assert.equal(h.document.activeElement.dataset.cityBuilding,'2');assert(labels.contains(h.document.activeElement));
  h.elements.cityBuildings.listeners.click({target:{closest:()=>({dataset:{cityBuilding:'all'}})}});h.run('drawCity()');
  assert.equal(labels.buttons.length,2);
  h.run('renderCityRooms([]);drawCity()');assert.equal(labels.innerHTML,'');
});
test('pedestrian routes reach visible doors without crossing offices, houses, shops or schools',()=>{
  const h=harness();
  for(const count of [17,33,65,160]) {
    const buildings=h.env.cityLayout(catalogue(count)),scenery=h.env.citySurroundings(buildings);
    const obstacles=[...buildings.map(b=>({x:b.x,y:b.y,w:220,d:120,name:`building ${b.number}`})),
      ...scenery.flatMap(s=>[{...s,name:s.title||s.kind},...(s.kind==='school'?
        [{x:s.x+s.w/2-21,y:s.y+s.d,w:42,d:13,name:'school entrance'}]:[])])];
    for(const b of buildings) {
      const entrance=h.env.cityEntrance(b),end=h.env.cityWalk(b,1);
      assert(Math.hypot(end.x-entrance.x,end.y-entrance.y)<1e-6,`route must reach door of building ${b.number}`);
      assert.equal(entrance.side,b.near);
      assert(b.near?entrance.x>b.x+220:entrance.y>b.y+120,'entrance must lie on a visible outside face');
      let previous=null;
      for(let step=0;step<=200;step++) {
        const point=h.env.cityWalk(b,step/200);
        assert(Number.isFinite(point.x)&&Number.isFinite(point.y));
        for(const obstacle of obstacles)assert(!(point.x>obstacle.x&&point.x<obstacle.x+obstacle.w&&point.y>obstacle.y&&point.y<obstacle.y+obstacle.d),
          `route to building ${b.number} crosses ${obstacle.name} at (${obstacle.x},${obstacle.y}), t=${step/200}`);
        if(previous)assert(Math.hypot(point.x-previous.x,point.y-previous.y)<10,'walking route cannot teleport');
        previous=point;
      }
    }
  }
});
test('building focus and floor navigation remain linked across live updates',()=>{
  const h=harness();h.env.fixture=catalogue(33);h.run('renderCityRooms(fixture)');
  assert.equal(h.elements.cityBuildings.hidden,false);
  h.elements.cityBuildings.listeners.click({target:{closest:()=>({dataset:{cityBuilding:'2'}})}});
  assert.equal(h.run('city.focus'),2);
  h.run('citySelect("office-17",true);drawCity()');assert.equal(h.run('city.focus'),2);
  assert(h.elements.cityPreview.innerHTML.includes('Корпус 2 · этаж 1'));
  h.run('renderCityRooms(fixture)');assert.equal(h.run('city.focus'),2);assert.equal(h.run('city.selected'),'office-17');
  h.elements.cityBuildings.listeners.click({target:{closest:()=>({dataset:{cityBuilding:'1'}})}});
  assert.equal(h.run('city.selected'),null);assert.equal(h.elements.cityPreview.hidden,true);
  h.run('citySelect("office-33",true)');assert.equal(h.run('city.focus'),3);
  h.env.fixture=catalogue(16);h.run('renderCityRooms(fixture)');assert.equal(h.run('city.focus'),null);
  assert.equal(h.elements.cityBuildings.hidden,true);
  h.run('citySelect("office-1",true)');assert.equal(h.elements.cityBuildings.hidden,false,'zooming a single building still offers the district view');
  h.elements.cityBuildings.listeners.click({target:{closest:()=>({dataset:{cityBuilding:'all'}})}});
  assert.equal(h.run('city.focus'),null);
});
test('hover opens the actual office and crossing the street to the preview does not dismiss it',()=>{
  const h=harness();h.env.fixture=rooms;h.run('renderCityRooms(fixture);drawCity()');
  const face=h.run('city.faces[0]'), center=face.points.reduce((p,q)=>[p[0]+q[0]/4,p[1]+q[1]/4],[0,0]);
  h.elements.cityCanvas.listeners.pointermove({clientX:center[0],clientY:center[1],pointerType:'mouse'});
  assert.equal(h.run('city.selected'),'api');assert.equal(h.elements.cityPreview.hidden,false);
  h.elements.cityCanvas.listeners.pointermove({clientX:1,clientY:1,pointerType:'mouse'});
  assert.equal(h.run('city.selected'),'api');
  h.elements.cityPreview.listeners.click({target:{closest:()=>({dataset:{cityAction:'open'}})}});
  assert.deepEqual(h.opened,['api']);
});
test('live updates retain selection and action focus; filters/removal close stale previews',()=>{
  const h=harness();h.env.fixture=rooms;h.run('renderCityRooms(fixture);citySelect("api")');
  h.elements.cityPreview.querySelector('[data-city-action="open"]').focus();
  h.env.lastSnapshot.daemons=[{id:'daemon',office_id:'api',office_slot:0,stage:'generating'}];
  h.run('renderCityRooms(fixture)');
  assert.equal(h.run('city.selected'),'api');assert.equal(h.document.activeElement.dataset.cityAction,'open');
  assert(h.elements.cityPreview.innerHTML.includes('1 из 12 мест · 1 работают'));
  assert(h.elements.cityPreview.innerHTML.includes('preview-demon'));
  h.env.rosterFilter.status='attention';h.env.lastSnapshot.daemons[0].match=false;h.run('renderCityRooms(fixture)');
  assert.equal(h.elements.cityPreview.hidden,true);assert.equal(h.run('city.selected'),null);
  h.env.rosterFilter.status='all';h.env.lastSnapshot.daemons[0].match=true;
  h.run('renderCityRooms(fixture);citySelect("api");renderCityRooms([])');
  assert.equal(h.elements.cityPreview.hidden,true);assert.equal(h.elements.cityFloors.innerHTML,'');
});
test('buttons support keyboard and touch selection; titles are escaped',()=>{
  const h=harness();h.env.fixture=[...rooms,{id:'x',title:'<img src=x onerror=alert(1)>',building_level:9,capacity:12}];
  h.run('renderCityRooms(fixture)');
  assert(!h.elements.cityFloors.innerHTML.includes('<img'));assert(h.elements.cityFloors.innerHTML.includes('&lt;img'));
  const button=h.elements.cityFloors.buttons[0];
  h.elements.cityFloors.listeners.click({target:{closest:()=>button}});assert.equal(h.run('city.selected'),'api');
  let prevented=false;
  h.elements.cityFloors.listeners.keydown({key:'End',target:button,preventDefault(){prevented=true;}});
  assert(prevented);assert.equal(h.run('city.selected'),'x');
  assert(h.elements.cityPreview.innerHTML.includes('&lt;img'));
  h.elements.cityStage.listeners.keydown({key:'Escape'});assert.equal(h.run('city.selected'),null);
});
test('pause, reduced motion, hidden tabs and offscreen scene stop the animation clock and paints',()=>{
  const h=harness();h.env.fixture=rooms;h.run('renderCityRooms(fixture);cityFrame(1000);cityFrame(1050)');
  const t=h.run('city.time');assert(t>8);
  h.elements.cityMotion.listeners.click();assert.deepEqual(h.writes,[['artel-motion-paused',true]]);
  h.run('cityFrame(1100)');const draws=h.draws.length;h.run('cityFrame(1200)');
  assert.equal(h.run('city.time'),t);assert.equal(h.draws.length,draws);
  h.env.social.paused=false;h.env.social.reduced.matches=true;h.run('cityFrame(1300)');assert.equal(h.run('city.time'),t);
  assert.equal(h.elements.cityMotion.disabled,true);
  h.env.social.reduced.matches=false;h.document.hidden=true;h.run('cityFrame(1400)');assert.equal(h.run('city.time'),t);
  h.document.hidden=false;h.run('city.visible=false;cityFrame(1500)');assert.equal(h.run('city.time'),t);
  h.run('city.visible=true;cityFrame(1550)');assert(h.run('city.time')>t);
});
test('custom building names are escaped in controls, addresses and previews, and rename invalidates scene labels',()=>{
  const h=harness(),name='<svg onload="x">&\'🧰';
  h.env.fixture=catalogue(17).map(r=>({...r,building_title:r.building_level<=16?name:'Второй корпус'}));
  h.run('renderCityRooms(fixture);citySelect("office-1",true);drawCity();cityOpenNameEditor()');
  assert.equal(h.env.cityAddressLabel(h.env.fixture[0]),`${name} · этаж 1`);
  for(const id of ['cityBuildings','cityFloors','cityLabels','cityPreview','cityNameBuilding']) {
    assert(h.elements[id].innerHTML.includes(h.env.esc(name)),`${id} must contain the escaped name`);
    assert(!h.elements[id].innerHTML.includes('<svg'),`${id} must never create markup from a name`);
  }
  assert.equal(h.elements.cityDistrictSummary.textContent,`${name} · до 16 офисов`);
  const key=h.run('city.labelKey'),positions=h.run('JSON.stringify(city.buildings.map(b=>[b.number,b.x,b.y,b.floors]))');
  h.env.fixture=h.env.fixture.map(r=>({...r,building_title:r.building_level<=16?'Платформа & API':r.building_title}));
  h.run('renderCityRooms(fixture);drawCity()');
  assert.notEqual(h.run('city.labelKey'),key);
  assert(h.elements.cityLabels.innerHTML.includes('Платформа &amp; API'));assert(!h.elements.cityLabels.innerHTML.includes('&lt;svg'));
  assert.equal(h.run('JSON.stringify(city.buildings.map(b=>[b.number,b.x,b.y,b.floors]))'),positions,'a name must not relocate any office');
  h.env.rosterFilter.query='платформа';h.run('renderCityRooms(fixture)');assert.equal(h.run('city.eligible.size'),16,'building names participate in office search');
});
test('sixty-character Unicode names remain accessible without overlapping or overflowing labels',()=>{
  const h=harness();
  for(const count of [17,65,160])for(const width of [280,390,840,900,1200]) {
    const fixture=catalogue(count).map(r=>({...r,building_title:(Math.ceil(r.building_level/16)%2?'🧰':'Ш').repeat(60)}));
    const buildings=h.env.cityLayout(fixture),height=width<=840?420:600;
    for(const focus of [null,2]) {
      const camera=h.env.cityCamera(width,height,buildings,h.env.citySurroundings(buildings),focus),labels=h.env.cityLabels(camera,buildings,focus),area=camera.labelArea;
      for(const [i,label] of labels.entries()) {
        const context=`${count} offices, ${width}px, focus ${focus}, label ${label.number}`;
        assert.equal(Array.from(label.text).length,60,context);
        assert.equal(label.text,buildings.find(b=>b.number===label.number).title,context);
        assert(label.x>=area.left&&label.x+label.w<=area.right+1e-6,context);
        assert(label.y>=area.top&&label.y+label.h<=area.bottom+1e-6,context);
        for(const previous of labels.slice(0,i))assert(!rectsOverlap(label,previous),`${context} overlaps ${previous.number}`);
      }
    }
  }
  const name='🧰'.repeat(60);h.env.fixture=catalogue(17).map(r=>({...r,building_title:name}));
  h.run('renderCityRooms(fixture);drawCity()');
  assert(h.elements.cityLabels.innerHTML.includes(`title="${name} · корпус 2"`),'ellipsis must retain the full hover title');
  assert(h.elements.cityLabels.innerHTML.includes(`aria-label="Приблизить корпус 2: ${name}"`),'assistive technology must retain the full name');
});
test('rename drafts survive live snapshots, target changes load names, and cancel never saves',()=>{
  const h=harness();h.env.fixture=catalogue(17).map(r=>({...r,building_title:r.building_level<=16?'Платформа':'Продукт'}));
  h.run('renderCityRooms(fixture);citySelect("office-17",true)');h.elements.cityRenameOpen.listeners.click();
  assert.equal(h.elements.cityNameBuilding.value,'2');assert.equal(h.elements.cityNameInput.value,'Продукт');
  assert.equal(h.document.activeElement,h.elements.cityNameInput);assert.equal(h.elements.cityNameInput.selectionEnd,'Продукт'.length);
  h.elements.cityNameBuilding.value='1';h.elements.cityNameBuilding.listeners.change();assert.equal(h.elements.cityNameInput.value,'Платформа');
  h.elements.cityNameInput.value='Мой несохранённый черновик';h.elements.cityNameInput.selectionStart=7;
  h.env.fixture=h.env.fixture.map(r=>({...r,building_title:r.building_level<=16?'Внешнее обновление':'Продукт'}));
  h.run('renderCityRooms(fixture);drawCity()');
  assert.equal(h.elements.cityNameInput.value,'Мой несохранённый черновик');assert.equal(h.elements.cityNameInput.selectionStart,7);
  assert.equal(h.elements.cityNameBuilding.value,'1');assert.equal(h.elements.cityNameForm.hidden,false);
  h.elements.cityNameCancel.listeners.click();assert.equal(h.requests.length,0);assert.equal(h.elements.cityNameForm.hidden,true);
  assert.equal(h.document.activeElement,h.elements.cityRenameOpen);assert.equal(h.elements.cityRenameOpen['aria-expanded'],'false');
  h.elements.cityRenameOpen.listeners.click();let prevented=false;
  h.elements.cityNameForm.listeners.keydown({key:'Escape',preventDefault(){prevented=true;}});
  assert(prevented);assert.equal(h.requests.length,0);assert.equal(h.elements.cityNameForm.hidden,true);
});
test('rename failures retain the draft and restore enabled controls for retry',async()=>{
  for(const offline of [false,true]) {
    const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);cityOpenNameEditor()');
    h.elements.cityNameInput.value='  Название для повторной попытки  ';
    h.setFetch(()=>{if(offline)throw new Error('Сеть недоступна');return {ok:false,json:async()=>({error:'Корпус недоступен'})};});
    await h.elements.cityNameForm.listeners.submit({preventDefault(){}});
    assert.equal(h.requests.length,1);assert.equal(h.applied.length,0);
    assert.equal(h.elements.cityNameInput.value,'  Название для повторной попытки  ');
    assert.equal(h.elements.cityNameStatus.textContent,offline?'Сеть недоступна':'Корпус недоступен');
    assert.equal(h.elements.cityNameForm.hidden,false);assert.equal(h.elements.cityNameForm['aria-busy'],'false');
    assert.equal(h.run('city.naming'),true);assert.equal(h.run('city.savingName'),false);
    for(const id of ['cityNameBuilding','cityNameInput','cityNameSave','cityNameCancel','cityRenameOpen'])assert.equal(h.elements[id].disabled,false,id);
  }
});
test('double submit makes one rename request, applies the snapshot and returns focus when saved',async()=>{
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);citySelect("office-17",true);cityOpenNameEditor()');
  const name='🧰'.repeat(60);h.elements.cityNameInput.value=`  ${name}  `;
  let finish;h.setFetch(()=>new Promise(resolve=>{finish=resolve;}));
  const event={preventDefault(){}},first=h.elements.cityNameForm.listeners.submit(event),second=h.elements.cityNameForm.listeners.submit(event);
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/buildings');assert.equal(h.requests[0].method,'POST');
  assert.deepEqual(JSON.parse(h.requests[0].body),{action:'rename',building:2,name});
  assert.equal(h.elements.cityNameForm['aria-busy'],'true');assert.equal(h.run('city.savingName'),true);
  for(const id of ['cityNameBuilding','cityNameInput','cityNameSave','cityNameCancel','cityRenameOpen'])assert.equal(h.elements[id].disabled,true,id);
  h.env.cityCloseNameEditor();assert.equal(h.elements.cityNameForm.hidden,false,'cannot dismiss a pending save');
  const snap={daemons:[],offices:h.env.fixture.map(r=>({...r,building_title:r.building_level>16?name:'Корпус 1'}))};
  finish({ok:true,json:async()=>snap});await Promise.all([first,second]);
  assert.equal(h.applied.length,1);assert.equal(h.applied[0],snap);assert.equal(h.requests.length,1);
  assert.equal(h.elements.cityNameForm.hidden,true);assert.equal(h.run('city.naming'),false);assert.equal(h.run('city.savingName'),false);
  assert.equal(h.elements.cityNameForm['aria-busy'],'false');assert.equal(h.document.activeElement,h.elements.cityRenameOpen);
  assert.equal(h.elements.cityNameStatus.textContent,'Название корпуса сохранено');
  for(const id of ['cityNameBuilding','cityNameInput','cityNameSave','cityNameCancel','cityRenameOpen'])assert.equal(h.elements[id].disabled,false,id);
  h.run('drawCity()');assert(h.elements.cityLabels.innerHTML.includes(name));
});
test('invalid names never send requests and empty catalogues cannot open the editor',async()=>{
  const h=harness();h.run('renderCityRooms([]);cityOpenNameEditor()');
  assert.equal(h.elements.cityRenameOpen.disabled,true);assert.equal(h.elements.cityNameForm.hidden,true);
  h.env.fixture=catalogue(1);h.run('renderCityRooms(fixture);cityOpenNameEditor()');
  for(const name of ['   ','Я'.repeat(61),'🧰'.repeat(61),'Название\nкорпуса','Корпус\u0000']) {
    h.elements.cityNameInput.value=name;await h.elements.cityNameForm.listeners.submit({preventDefault(){}});
    assert.match(h.elements.cityNameStatus.textContent,/от 1 до 60 символов/);assert.equal(h.requests.length,0);
    assert.equal(h.elements.cityNameForm.hidden,false);assert.equal(h.elements.cityNameInput.disabled,false);
  }
});
test('zoom preserves the world point beneath its anchor and clamps extreme views to a visible district',()=>{
  const h=harness();
  for(const count of [1,17,65])for(const width of [280,390,1200]) {
    const buildings=h.env.cityLayout(catalogue(count)),base=h.env.cityCamera(width,width<=840?420:600,buildings,h.env.citySurroundings(buildings));
    const center=[(base.area.left+base.area.right)/2,(base.area.top+base.area.bottom)/2],origin=base.project(0,0);
    const [u,v]=center.map((n,i)=>(n+[30,-22][i]-origin[i])/base.scale),world=[(u*.39+v*.54)/.4908,(v*.94-u*.23)/.4908,0];
    const initial={zoom:1.5,x:13,y:-7},anchor=h.env.cityViewCamera(base,initial).project(...world);
    for(const zoom of [.75,2,4]) {
      const next=h.env.cityZoomAt(base,initial,zoom,anchor),position=h.env.cityViewCamera(base,next).project(...world);
      near(position[0],anchor[0],'zoom anchor x');near(position[1],anchor[1],'zoom anchor y');near(next.zoom,zoom,'requested zoom');
    }
    const objectAnchor=h.env.cityZoomAt(base,initial,2,{x:anchor[0],y:anchor[1]});
    const arrayAnchor=h.env.cityZoomAt(base,initial,2,anchor);
    near(objectAnchor.x,arrayAnchor.x,'object and array anchors agree');near(objectAnchor.y,arrayAnchor.y,'object and array anchors agree');
    for(const proposed of [{zoom:99,x:1e12,y:-1e12},{zoom:-9,x:-1e12,y:1e12},{zoom:NaN,x:Infinity,y:NaN}]) {
      const view=h.env.cityClampView(base,proposed),camera=h.env.cityViewCamera(base,view),zero=camera.project(0,0);
      assert(view.zoom>=.5&&view.zoom<=8);assert(Object.values(view).every(Number.isFinite));
      for(const [i,lo,hi,start,end] of [[0,base.bounds.left,base.bounds.right,base.area.left,base.area.right],[1,base.bounds.top,base.bounds.bottom,base.area.top,base.area.bottom]]) {
        const lower=zero[i]+lo*camera.scale,upper=zero[i]+hi*camera.scale;
        const visible=Math.min(end,upper)-Math.max(start,lower);
        assert(visible>=Math.min(36,(upper-lower)/2)-1e-6,'panning cannot hide the entire district');
      }
    }
  }
});
test('zoomed and panned picking follows rendered facades and live snapshots preserve the view',()=>{
  for(const width of [390,1200]) {
    const h=harness(width,width<=840?420:600);h.env.fixture=catalogue(33);
    h.run('renderCityRooms(fixture);drawCity()');const previousKey=h.run('city.labelKey');
    h.run('citySetView({zoom:2,x:30,y:-18});drawCity()');
    assert.notEqual(h.run('city.labelKey'),previousKey,'camera movements update overlay labels');
    const faces=h.run('city.faces'),area=h.run('cityBaseCamera().area');let tested=0;
    for(const face of faces) {
      const center=faceCenter(face);
      if(center[0]<area.left||center[0]>area.right||center[1]<area.top||center[1]>area.bottom)continue;
      assert.equal(h.env.cityPick({clientX:center[0],clientY:center[1]}),face.id);tested++;
    }
    assert(tested>0,'camera fixture must retain selectable visible floors');
    const before=viewValues(h);h.env.fixture=h.env.fixture.map(r=>({...r,title:'Название после SSE'}));
    h.env.lastSnapshot.daemons=[{id:'worker',office_id:'office-1',stage:'generating'}];
    h.run('renderCityRooms(fixture);drawCity()');assert.deepEqual(viewValues(h),before);
  }
});
test('a focused camera can pan to the farthest building at the same zoom on mobile and desktop',()=>{
  for(const width of [280,390,1200])for(const focus of [1,10]) {
    const h=harness(width,width<=840?420:600);h.env.fixture=catalogue(160);h.env.focusNumber=focus;
    h.run('renderCityRooms(fixture);city.focus=focusNumber;drawCity()');
    const base=h.env.cityBaseCamera(),targetNumber=focus===1?10:1;
    const target=h.run('city.buildings').find(b=>b.number===targetNumber),world=[target.x+110,target.y+120.5,(56+31)*h.run('CITY_HEIGHT')];
    const initial=base.project(...world),center=[(base.area.left+base.area.right)/2,(base.area.top+base.area.bottom)/2];
    assert(initial[0]<base.area.left||initial[0]>base.area.right,'fixture must start with the farthest building outside the focused frame');
    assert(base.panBounds.right-base.panBounds.left>base.bounds.right-base.bounds.left,'pan bounds must span the district independently of focused framing');
    h.env.citySetView({zoom:1,x:center[0]-initial[0],y:center[1]-initial[1]});h.run('drawCity()');
    assert.equal(viewValues(h).zoom,1);assert.equal(h.run('city.focus'),focus);
    const targetId=target.rooms[0].room.id,face=h.run('city.faces').find(f=>f.id===targetId);
    assert(face,`building ${targetNumber} must enter the rendered scene after panning from ${focus} at ${width}px`);
    const at=faceCenter(face);near(at[0],center[0],'far building reaches viewport center x');near(at[1],center[1],'far building reaches viewport center y');
    assert.equal(h.env.cityPick({clientX:at[0],clientY:at[1]}),targetId,'far office remains selectable');
    assert(h.run('city.labels').some(label=>label.number===targetNumber),'far building name appears during focused panning');
  }
});
test('dragging either a facade or a label does not select an office or activate a building',()=>{
  for(const startOnLabel of [false,true]) {
    const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);drawCity()');
    const face=h.run('city.faces[0]'),[x,y]=faceCenter(face),label=h.elements.cityLabels.buttons.find(b=>b.dataset.cityBuilding==='2');
    pointer(h,'pointerdown',{x,y,target:startOnLabel?label:h.elements.cityCanvas});
    assert.equal(h.run('city.dragging'),true);assert(h.elements.cityCanvas.hasPointerCapture(1));
    h.clock(2000); // Hover suppression must hold even after the initial grace period expires.
    pointer(h,'pointermove',{x:x+2,y:y+2});assert.deepEqual(viewValues(h),{zoom:1,x:0,y:0},'small jitter remains a tap');
    pointer(h,'pointermove',{x:x+40,y:y+25});
    assert(h.elements.cityViewport.classList.contains('is-dragging'));assert.equal(h.run('city.selected'),null);
    pointer(h,'pointerup',{x:x+40,y:y+25});h.run('drawCity()');
    assert.equal(h.run('city.dragging'),false);assert.equal(h.elements.cityCanvas.captures.size,0);
    assert.equal(h.elements.cityViewport.classList.contains('is-dragging'),false);
    const moved=h.run('city.faces.find(f=>f.id==="office-1")'),at=faceCenter(moved);
    h.elements.cityCanvas.listeners.click({clientX:at[0],clientY:at[1],detail:1});
    h.elements.cityLabels.listeners.click({detail:1,target:label});
    assert.equal(h.run('city.selected'),null);assert.equal(h.run('city.focus'),null);
    h.elements.cityLabels.listeners.click({detail:0,target:label});assert.equal(h.run('city.focus'),2,'keyboard activation is not suppressed');
  }
});
test('a captured label tap focuses once and the following native click cannot reset a newer camera view',()=>{
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);drawCity()');
  const label=h.elements.cityLabels.buttons.find(b=>b.dataset.cityBuilding==='2');
  pointer(h,'pointerdown',{pointerType:'touch',target:label});pointer(h,'pointerup',{pointerType:'touch'});
  assert.equal(h.run('city.focus'),2);assert.equal(h.run('city.dragging'),false);
  h.env.cityZoomBy(1.35);const before=viewValues(h);
  h.elements.cityLabels.listeners.click({detail:1,target:label});assert.deepEqual(viewValues(h),before);
});
test('pinch-to-pan transition rebases the remaining finger without a jump or stale capture',()=>{
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture)');
  pointer(h,'pointerdown',{id:1,x:180,y:230,pointerType:'touch'});
  pointer(h,'pointerdown',{id:2,x:320,y:230,pointerType:'touch'});
  pointer(h,'pointermove',{id:2,x:360,y:230,pointerType:'touch'});
  const pinched=viewValues(h);assert(pinched.zoom>1);
  pointer(h,'pointerup',{id:1,x:180,y:230,pointerType:'touch'});
  assert.equal(h.elements.cityCanvas.hasPointerCapture(1),false);assert(h.elements.cityCanvas.hasPointerCapture(2));
  assert.equal(h.run('city.dragging'),true);
  pointer(h,'pointermove',{id:2,x:360,y:230,pointerType:'touch'});assert.deepEqual(viewValues(h),pinched,'lifting one finger must not move the scene');
  pointer(h,'pointermove',{id:2,x:370,y:230,pointerType:'touch'});
  near(viewValues(h).zoom,pinched.zoom,'one remaining finger pans without zoom');near(viewValues(h).x,pinched.x+10,'remaining finger follows delta');
  pointer(h,'pointerup',{id:2,x:370,y:230,pointerType:'touch'});assert.equal(h.run('city.dragging'),false);assert.equal(h.elements.cityCanvas.captures.size,0);
});
test('pointer cancellation, lost capture and window blur release every finger and clean drag state',()=>{
  for(const ending of ['pointercancel','lostpointercapture','blur']) {
    const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture)');
    pointer(h,'pointerdown',{id:1,x:180,pointerType:'touch'});pointer(h,'pointerdown',{id:2,x:320,pointerType:'touch'});
    pointer(h,'pointermove',{id:2,x:350,pointerType:'touch'});assert(h.elements.cityViewport.classList.contains('is-dragging'));
    if(ending==='pointercancel')pointer(h,ending,{id:1,pointerType:'touch'});
    else if(ending==='lostpointercapture') {h.elements.cityCanvas.captures.delete(1);h.elements.cityCanvas.listeners.lostpointercapture({pointerId:1});}
    else h.env.window.listeners.blur();
    assert.equal(h.elements.cityCanvas.captures.size,0,ending);assert.equal(h.run('city.dragging'),false,ending);
    assert.equal(h.elements.cityViewport.classList.contains('is-dragging'),false,ending);assert.equal(h.elements.cityCanvas.style.cursor,'');
    const stopped=viewValues(h);pointer(h,'pointermove',{id:2,x:500,pointerType:'touch'});assert.deepEqual(viewValues(h),stopped,'ended gestures cannot resume');
    assert(h.env.cityIgnoreClick({detail:1}));
    pointer(h,'pointerdown',{id:3,x:200,pointerType:'touch'});pointer(h,'pointermove',{id:3,x:220,pointerType:'touch'});
    assert.equal(h.run('city.dragging'),true,'next gesture must work');pointer(h,'pointerup',{id:3,x:220,pointerType:'touch'});
  }
});
test('wheel units are normalized, browser scrolling is prevented and wheels cannot perturb a pointer gesture',()=>{
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture)');
  assert.equal(h.elements.cityViewport.listenerOptions.wheel.passive,false);
  const wheel=(deltaY,deltaMode=0,ctrlKey=false)=>{
    let prevented=false;h.elements.cityViewport.listeners.wheel({clientX:400,clientY:250,deltaY,deltaMode,ctrlKey,preventDefault(){prevented=true;}});
    assert(prevented);return viewValues(h);
  };
  const pixel=wheel(-16);h.env.cityResetView();const line=wheel(-1,1);assert.deepEqual(line,pixel);
  h.env.cityResetView();const page=wheel(1,2);h.env.cityResetView();const capped=wheel(240);assert.deepEqual(page,capped);
  h.env.cityResetView();const ordinary=wheel(-40);h.env.cityResetView();const trackpadPinch=wheel(-40,0,true);assert(trackpadPinch.zoom>ordinary.zoom);
  const before=viewValues(h);wheel(0);assert.deepEqual(viewValues(h),before);
  pointer(h,'pointerdown');wheel(-100);assert.deepEqual(viewValues(h),before);pointer(h,'pointerup');
});
test('keyboard and zoom buttons obey limits, Home restores the district, and animation pause does not disable navigation',()=>{
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);citySelect("office-17",true)');
  const key=(value,extra={})=>{let prevented=false;h.elements.cityCanvas.listeners.keydown({key:value,...extra,preventDefault(){prevented=true;}});return prevented;};
  assert(key('+'));assert(viewValues(h).zoom>1);const zoomed=viewValues(h);
  assert(key('ArrowLeft'));near(viewValues(h).x,zoomed.x+70,'left arrow moves map right');
  const moved=viewValues(h);assert.equal(key('+',{ctrlKey:true}),false);assert.deepEqual(viewValues(h),moved);
  assert.equal(key('Tab'),false);assert(key('Home'));assert.deepEqual(viewValues(h),{zoom:1,x:0,y:0});
  assert.equal(h.run('city.focus'),null);assert.equal(h.run('city.selected'),null);assert.equal(h.elements.cityZoomValue.textContent,'100%');
  for(let i=0;i<20;i++)h.elements.cityZoomIn.listeners.click();assert.equal(viewValues(h).zoom,8);assert.equal(h.elements.cityZoomIn.disabled,true);
  for(let i=0;i<30;i++)h.elements.cityZoomOut.listeners.click();assert.equal(viewValues(h).zoom,.5);assert.equal(h.elements.cityZoomOut.disabled,true);
  h.elements.cityReset.listeners.click();assert.deepEqual(viewValues(h),{zoom:1,x:0,y:0});
  h.env.social.paused=true;h.run('cityFrame(1000)');const time=h.run('city.time'),paints=h.draws.length;
  h.elements.cityZoomIn.listeners.click();h.run('cityFrame(1050)');assert(h.draws.length>paints);assert.equal(h.run('city.time'),time);
  pointer(h,'pointerdown',{x:200});pointer(h,'pointermove',{x:230});pointer(h,'pointerup',{x:230});h.run('cityFrame(1100)');
  assert(viewValues(h).x!==0);assert.equal(h.run('city.time'),time);
});
test('drag and pinch reverse immediately after hitting pan or zoom limits',()=>{
  for(const direction of [-1,1]) {
    const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture)');
    pointer(h,'pointerdown',{x:200});pointer(h,'pointermove',{x:direction*10000});
    const edge=viewValues(h);pointer(h,'pointermove',{x:direction*10000-direction*10});
    near(viewValues(h).x,edge.x-direction*10,'reversing must not require undoing invisible overshoot');
    pointer(h,'pointerup',{x:direction*10000-direction*10});
  }
  const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture)');
  pointer(h,'pointerdown',{id:1,x:180,pointerType:'touch'});pointer(h,'pointerdown',{id:2,x:320,pointerType:'touch'});
  pointer(h,'pointermove',{id:2,x:2000,pointerType:'touch'});assert.equal(viewValues(h).zoom,8);
  pointer(h,'pointermove',{id:2,x:1990,pointerType:'touch'});assert(viewValues(h).zoom<8&&viewValues(h).zoom>7,'pinching back reacts at the zoom limit');
  pointer(h,'pointerup',{id:1,x:180,pointerType:'touch'});pointer(h,'pointerup',{id:2,x:1990,pointerType:'touch'});
});
test('Home, zoom, focus, resize and external camera updates cancel active gestures before changing the view',()=>{
  for(const action of ['Home','zoom','focus','resize','setView','reset']) {
    const h=harness();h.env.fixture=catalogue(17);h.run('renderCityRooms(fixture);drawCity()');
    const label=h.elements.cityLabels.buttons.find(b=>b.dataset.cityBuilding==='2');
    pointer(h,'pointerdown',{x:200,target:label});pointer(h,'pointermove',{x:240});assert.equal(h.run('city.dragging'),true);
    if(action==='Home')h.elements.cityCanvas.listeners.keydown({key:'Home',preventDefault(){}});
    if(action==='zoom')h.elements.cityZoomIn.listeners.click();
    if(action==='focus')h.elements.cityLabels.listeners.click({detail:0,target:label});
    if(action==='resize') {h.elements.cityCanvas.getBoundingClientRect=()=>({width:1000,height:560,left:0,top:0});h.env.cityResize();}
    if(action==='setView')h.env.citySetView({zoom:2,x:12,y:-8});
    if(action==='reset')h.elements.cityReset.listeners.click();
    assert.equal(h.run('city.dragging'),false,action);assert.equal(h.elements.cityCanvas.captures.size,0,action);
    assert.equal(h.elements.cityViewport.classList.contains('is-dragging'),false,action);
    const expected=viewValues(h),focused=h.run('city.focus');
    pointer(h,'pointermove',{x:350});pointer(h,'pointerup',{x:350});
    assert.deepEqual(viewValues(h),expected,`${action}: stale movement must not restore the old gesture`);
    assert.equal(h.run('city.focus'),focused,`${action}: a cancelled label gesture must not activate later`);
  }
});
