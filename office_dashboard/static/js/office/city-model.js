'use strict';
/* The persisted ordinal is an address, not a count: deleting/filtering an office
   must never move its neighbours to another building. No browser-only allocation. */
const CITY_FLOORS = 16;
const CITY_HEIGHT = .65;
const CITY_ZOOM_MIN = .5;
const CITY_ZOOM_MAX = 8;
function cityAddress(room, fallback=1) {
  const level = Number.isSafeInteger(room.building_level) && room.building_level>0 ? room.building_level : fallback;
  return {building:Math.floor((level-1)/CITY_FLOORS)+1, floor:(level-1)%CITY_FLOORS+1};
}
function cityAddressLabel(room, fallback=1) {
  const a=cityAddress(room,fallback);return `${cityRoomBuildingTitle(room,fallback)} · ${tr('этаж', 'floor')} ${a.floor}`;
}
function cityRoomBuildingTitle(room, fallback=1) {
  return room.building_title_custom !== false && typeof room.building_title==='string' && room.building_title.trim() ? room.building_title : `${tr('Корпус', 'Building')} ${cityAddress(room,fallback).building}`;
}
function cityLayout(rooms) {
  const groups=new Map();
  const sorted=[...rooms].sort((a,b)=>(a.building_level||0)-(b.building_level||0)||a.id.localeCompare(b.id));
  sorted.forEach((room,i)=>{
    const address=cityAddress(room,i+1), number=address.building;
    if(!groups.has(number)) {
      const near=number%2===0, y=near?520:0;
      // Offset the opposite frontage so towers never cover each other's facades.
      groups.set(number,{number,title:cityRoomBuildingTitle(room,i+1),near,x:(number-1)*500+y*.54/.94,y,rooms:[],floors:1});
    }
    const b=groups.get(number);b.rooms.push({room,floor:address.floor});b.floors=Math.max(b.floors,address.floor);
  });
  return [...groups.values()];
}
function cityPopulation(count) {
  const n=Math.max(1,count);
  return {cars:2*n,people:5*n-2,houses:2*n+1,shops:n+1,schools:1+Math.floor((n-1)/4)};
}
function citySurroundings(buildings) {
  const result=[];
  // Lots are aligned in the camera's horizontal projection. The 156-unit gaps
  // between office silhouettes stay clear at every height and on either bank.
  const lot=(kind,left,y,w,d,h,extra={})=>({kind,x:(left+.54*(y+d))/.94,y,w,d,h,...extra});
  buildings.forEach((b,i)=>{
    const k=cityIso(b.x,b.y)[0], left=k+234;
    result.push(lot('house',left,-180,92,75,80+(i%3)*15),
      // On the south bank the shop stands on the pavement in front; its house steps aside so the sign stays visible.
      lot('house',b.near?left+168:left,580,98,82,105+(i%2)*18),
      lot('shop',left,b.near?448:174,112,70,40,{title:i%2?tr("КАФЕ", "CAFE"):tr("МАГАЗИН", "SHOP")}));
    if(i%4===0)result.push(lot('school',k-244,-400,190,92,63,{title:tr("ШКОЛА", "SCHOOL")}));
  });
  const first=buildings[0];
  if(first) {
    const k=cityIso(first.x,first.y)[0];
    result.push(lot('house',k-222,-80,85,78,97),lot('shop',k-230,130,100,65,36,{title:tr("ПЕКАРНЯ", "BAKERY")}));
  }
  return result;
}
/* The district reacts to what daemons report. Only events newer than the first snapshot
   become reactions; history seeds the weather but is never replayed as animation. */
const CITY_WEATHER_WINDOW = 900;
const CITY_REACTIONS = ['generating','rework','git','success','error'];
const cityPulse = {ready:false, seen:new Map(), errors:[], deliveries:[], feed:[], done:new Map()};
function cityIngest(daemons, now) {
  const fresh=[], first=!cityPulse.ready;
  for(const d of daemons) {
    const events=Array.isArray(d.events)?d.events.filter(e=>Number.isFinite(e?.t)):[];
    const known=cityPulse.seen.has(d.id), since=cityPulse.seen.get(d.id) ?? -Infinity;
    for(const e of events) {
      if(e.t<=since||!CITY_REACTIONS.includes(e.stage))continue;
      const item={id:d.id,name:d.name||d.id,office:d.office_id,stage:e.stage,issue:e.issue||d.issue||'',result:e.result||null,t:e.t};
      if(e.stage==='error')cityPulse.errors.push(item);
      if(e.stage==='success')cityPulse.deliveries.push(item);
      cityPulse.feed.push(item);
      // A daemon seen for the first time brings its history, not news.
      if(!first&&known)fresh.push(item);
    }
    const last=d.last_error;
    if(Number.isFinite(last?.t)&&last.t>since&&!events.some(e=>e.stage==='error'&&Math.abs(e.t-last.t)<2))
      cityPulse.errors.push({id:d.id,name:d.name||d.id,office:d.office_id,stage:'error',issue:last.issue||d.issue||'',t:last.t});
    cityPulse.seen.set(d.id,Math.max(since,...events.map(e=>e.t),Number.isFinite(last?.t)?last.t:-Infinity));
  }
  const horizon=now-CITY_WEATHER_WINDOW;
  const unique=list=>[...new Map(list.filter(e=>e.t>horizon).map(e=>[`${e.id}:${e.stage}:${e.t}`,e])).values()];
  cityPulse.errors=unique(cityPulse.errors);cityPulse.deliveries=unique(cityPulse.deliveries);
  cityPulse.feed=[...new Map(cityPulse.feed.map(e=>[`${e.id}:${e.stage}:${e.t}`,e])).values()].sort((a,b)=>a.t-b.t).slice(-12);
  cityPulse.ready=true;
  return fresh.sort((a,b)=>a.t-b.t);
}
// Weather is health over the last fifteen minutes: one cloud per error, a lost daemon weighs double.
function cityHealth(buildings, daemons, now, attention=d=>d.alive===false&&d.stage!=='stopped') {
  const officeBuilding=new Map(buildings.flatMap(b=>b.rooms.map(({room})=>[room.id,b.number])));
  const health=new Map(buildings.map(b=>[b.number,{errors:0,attention:0,delivered:0,level:0}]));
  for(const e of cityPulse.errors)if(e.t>now-CITY_WEATHER_WINDOW)health.get(officeBuilding.get(e.office))&&health.get(officeBuilding.get(e.office)).errors++;
  for(const e of cityPulse.deliveries)if(e.t>now-CITY_WEATHER_WINDOW)health.get(officeBuilding.get(e.office))&&health.get(officeBuilding.get(e.office)).delivered++;
  for(const d of daemons)if(attention(d))health.get(officeBuilding.get(d.office_id))&&health.get(officeBuilding.get(d.office_id)).attention++;
  for(const h of health.values()) {
    const score=h.errors+2*h.attention;
    h.level=score>=5?3:score>=3?2:score>=1?1:0;
  }
  return health;
}
// Every tenth task delivered from a building is a milestone; the first snapshot only records the count.
function cityMilestones(buildings, daemons) {
  const officeBuilding=new Map(buildings.flatMap(b=>b.rooms.map(({room})=>[room.id,b.number]))), totals=new Map(), reached=[];
  for(const d of daemons) {
    const n=officeBuilding.get(d.office_id);
    if(n!==undefined)totals.set(n,(totals.get(n)||0)+(Number(d.counters?.done)||0));
  }
  for(const [n,total] of totals) {
    const before=cityPulse.done.get(n);
    if(before!==undefined&&Math.floor(total/10)>Math.floor(before/10))reached.push({building:n,total:Math.floor(total/10)*10});
    cityPulse.done.set(n,total);
  }
  return reached;
}
// Lawn trees are seeded by position, so the grove is identical on every load and only grows with the district.
const cityGroveCache={key:'',trees:[]};
function cityGrove(buildings,scenery) {
  const key=buildings.map(b=>`${b.number}:${b.floors}`).join(',');
  if(key===cityGroveCache.key)return cityGroveCache.trees;
  const rand=(i,j,k)=>{const v=Math.sin(i*127.1+j*311.7+k*74.7)*43758.5453;return v-Math.floor(v);};
  const inside=(x,y,l,t,r,b)=>x>=l&&x<=r&&y>=t&&y<=b;
  const overlap=(a,b)=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
  const box=(x,y,w,d,h)=>{const pts=cityBounds(x,y,w,d,h),xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]);return {left:Math.min(...xs),right:Math.max(...xs),top:Math.min(...ys),bottom:Math.max(...ys)};};
  // Anything a tree must never stand in front of: office facades and the signage of shops and schools.
  const screens=[...buildings.map(b=>({depth:b.x+b.y+220,box:box(b.x-6,b.y-6,232,132,(92+b.floors*62)*CITY_HEIGHT)})),
    ...scenery.filter(s=>s.kind!=='house').map(s=>({depth:s.x+s.y+s.d,box:box(s.x-4,s.y-4,s.w+8,s.d+8,s.h+34)}))];
  const blocked=(x,y)=>buildings.some(b=>inside(x,y,b.x-70,b.y-70,b.x+300,b.y+235)||
      (b.near?inside(x,y,b.x+215,472,b.x+275,b.y):inside(x,y,b.x+85,b.y+120,b.x+140,206)))||
    scenery.some(s=>{
      const extra=s.kind==='school'?130:40;
      if(inside(x,y,s.x-42,s.y-42,s.x+s.w+42,s.y+s.d+extra))return true;
      const mid=s.x+s.w/2;
      return s.y+s.d<204?inside(x,y,mid-22,s.y+s.d,mid+22,206):s.y>472&&inside(x,y,mid-22,472,mid+22,s.y);
    });
  const left=Math.min(...buildings.map(b=>b.x))-900, right=Math.max(...buildings.map(b=>b.x))+1100, trees=[];
  const rows=[];for(let y=-620;y<=150;y+=62)rows.push(y);for(let y=530;y<=1060;y+=62)rows.push(y);
  for(const [j,row] of rows.entries())for(let i=0,x0=left;x0<=right;i++,x0+=62) {
    // A slow wave gathers trees into groves and leaves open meadows between them.
    const grove=(Math.sin(x0*.0045+j*.7)+Math.cos(row*.011+x0*.0023))/2;
    if(rand(i,j,1)>.06+.24*Math.max(0,grove))continue;
    const x=x0+(rand(i,j,2)-.5)*40, y=row+(rand(i,j,3)-.5)*34;
    if((row<204&&y>176)||(row>472&&y<506)||blocked(x,y))continue;
    const size=.78+rand(i,j,4)*.45, crown=box(x-22,y-22,44,44,(36+22)*size);
    if(screens.some(s=>x+y+10>s.depth&&overlap(crown,s.box)))continue;
    trees.push({x,y,size,kind:rand(i,j,5)<.22?'cypress':'round'});
  }
  cityGroveCache.key=key;cityGroveCache.trees=trees;
  return trees;
}
function cityIso(x,y,z=0) {return [x*.94-y*.54,x*.23+y*.39-z];}
function cityBounds(x,y,w,d,h) {
  return [[x,y,0],[x+w,y,0],[x,y+d,0],[x+w,y+d,0],
    [x,y,h],[x+w,y,h],[x,y+d,h],[x+w,y+d,h]].map(a=>cityIso(...a));
}
function cityDistrictBounds(buildings) {
  const points=[];
  for(const b of buildings)points.push(...cityBounds(b.x-12,b.y-12,244,145,(92+b.floors*62)*CITY_HEIGHT));
  // Office frontage sets the scale. Perimeter houses may recede beyond the
  // frame instead of shrinking the operational buildings to fit every prop.
  const left=Math.min(...buildings.map(b=>b.x))-160, right=Math.max(...buildings.map(b=>b.x))+340;
  points.push(cityIso(left,280),cityIso(right,472));
  const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
  return {left:Math.min(...xs),right:Math.max(...xs),top:Math.min(...ys),bottom:Math.max(...ys)};
}
function cityCamera(width,height,buildings,scenery=[],focus=null) {
  const mobile=width<=840, focused=buildings.find(b=>b.number===focus);
  const bounds=cityDistrictBounds(focused?[focused]:buildings);
  // Focus changes the initial framing, not the district that can be explored.
  const panBounds=focused?cityDistrictBounds(buildings):bounds;
  const area={left:mobile?16:28,right:mobile?width-16:width-(width>1100?388:330),top:mobile?84:96,bottom:height-(mobile?64:74)};
  const scale=Math.min(mobile?1.08:1.5,(area.right-area.left)/Math.max(1,bounds.right-bounds.left),(area.bottom-area.top)/Math.max(1,bounds.bottom-bounds.top));
  const ox=(area.left+area.right-(bounds.left+bounds.right)*scale)/2;
  const oy=(area.top+area.bottom-(bounds.top+bounds.bottom)*scale)/2;
  return {width,height,scale,bounds,panBounds,area,labelArea:{...area,bottom:height-16},project(x,y,z=0){const p=cityIso(x,y,z);return [ox+p[0]*scale,oy+p[1]*scale];}};
}
function cityClampView(base,view={}) {
  const finite=(value,fallback)=>Number.isFinite(value)?value:fallback;
  const zoom=Math.max(CITY_ZOOM_MIN,Math.min(CITY_ZOOM_MAX,finite(view.zoom,1)));
  const bounds=base.panBounds||base.bounds;
  const center=[(base.area.left+base.area.right)/2,(base.area.top+base.area.bottom)/2], origin=base.project(0,0);
  const clampAxis=(value,index,start,end,low,high)=>{
    const lo=center[index]+(origin[index]+low*base.scale-center[index])*zoom;
    const hi=center[index]+(origin[index]+high*base.scale-center[index])*zoom;
    // Leave an appreciable piece of the district in view, while allowing its
    // outer streets and scenery to be inspected from either side.
    const reach=Math.min(Math.max(36,(end-start)*.15),Math.max(1,(hi-lo)/2));
    return Math.max(start+reach-hi,Math.min(end-reach-lo,finite(value,0)));
  };
  return {zoom,x:clampAxis(view.x,0,base.area.left,base.area.right,bounds.left,bounds.right),
    y:clampAxis(view.y,1,base.area.top,base.area.bottom,bounds.top,bounds.bottom)};
}
function cityViewCamera(base,view={}) {
  const current=cityClampView(base,view),center=[(base.area.left+base.area.right)/2,(base.area.top+base.area.bottom)/2];
  return {...base,baseCamera:base,view:current,viewZoom:current.zoom,scale:base.scale*current.zoom,
    project(x,y,z=0) {
      const point=base.project(x,y,z);
      return [center[0]+(point[0]-center[0])*current.zoom+current.x,center[1]+(point[1]-center[1])*current.zoom+current.y];
    }};
}
function cityZoomAt(base,view,nextZoom,point) {
  const current=cityClampView(base,view),zoom=Math.max(CITY_ZOOM_MIN,Math.min(CITY_ZOOM_MAX,Number.isFinite(nextZoom)?nextZoom:current.zoom));
  const center=[(base.area.left+base.area.right)/2,(base.area.top+base.area.bottom)/2];
  const px=Array.isArray(point)?point[0]:point?.x,py=Array.isArray(point)?point[1]:point?.y;
  const anchor=[Number.isFinite(px)?px:center[0],Number.isFinite(py)?py:center[1]],ratio=zoom/current.zoom;
  return cityClampView(base,{zoom,x:anchor[0]-center[0]-(anchor[0]-center[0]-current.x)*ratio,
    y:anchor[1]-center[1]-(anchor[1]-center[1]-current.y)*ratio});
}
function cityLabels(camera,buildings,focus=null) {
  const area=camera.labelArea;
  const navigating=camera.view && (Math.abs(camera.view.zoom-1)>1e-6 || Math.abs(camera.view.x)>1e-6 || Math.abs(camera.view.y)>1e-6);
  const visible=(focus===null || navigating?buildings:buildings.filter(b=>b.number===focus)).filter(b=>{
    if(!navigating)return true;
    const anchor=camera.project(b.x+110,b.y+145);
    return anchor[0]>=area.left-64 && anchor[0]<=area.right+64 && anchor[1]>=area.top-64 && anchor[1]<=area.bottom+32;
  }), placed=[];
  const overlap=(a,b)=>a.x<b.x+b.w+4&&a.x+a.w+4>b.x&&a.y<b.y+b.h+4&&a.y+a.h+4>b.y;
  const facades=visible.map(b=>{
    const pts=cityBounds(b.x-6,b.y-6,232,132,(92+b.floors*62)*CITY_HEIGHT);
    const base=camera.project(0,0), xs=pts.map(p=>base[0]+p[0]*camera.scale), ys=pts.map(p=>base[1]+p[1]*camera.scale);
    return {x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys)};
  });
  for(const b of visible) {
    const text=b.title||`${tr('Корпус', 'Building')} ${b.number}`;
    const maxWidth=Math.min(168,visible.length>1?(area.right-area.left-8)/2:area.right-area.left);
    const anchor=camera.project(b.x+110,b.y+145), w=Math.min(maxWidth,Math.max(96,Array.from(text).length*7+24)),h=36;
    const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
    const preferred={x:clamp(anchor[0]-w/2,area.left,area.right-w),y:clamp(anchor[1]+12,area.top,area.bottom-h),w,h};
    const candidates=[preferred];
    if(navigating) {
      // Move with the building during a drag; a screen-fixed search grid would
      // make labels hop between unrelated places as the camera moves.
      for(const [dx,dy] of [[0,-h-24],[-w-8,0],[w+8,0],[0,h+8],[-w-8,-h-24],[w+8,-h-24]])
        candidates.push({x:clamp(preferred.x+dx,area.left,area.right-w),y:clamp(preferred.y+dy,area.top,area.bottom-h),w,h});
    } else for(let y=area.top;y<=area.bottom-h;y+=h+8)for(let x=area.left;x<=area.right-w;x+=w+8)candidates.push({x,y,w,h});
    const score=q=>Math.hypot(q.x-preferred.x,q.y-preferred.y)+facades.filter(f=>overlap(q,f)).length*(navigating?40:1000);
    const free=candidates.filter(q=>!placed.some(p=>overlap(q,p)));
    if(navigating&&!free.length)continue;
    const best=(free.length?free:candidates).sort((a,b)=>score(a)-score(b))[0];
    placed.push({...best,number:b.number,anchor,text});
  }
  return placed;
}
function cityEntrance(b) {return b.near?{x:b.x+221,y:b.y+38,side:true}:{x:b.x+112,y:b.y+121,side:false};}
function cityWalk(b,t) {
  const entrance=cityEntrance(b), pavement=b.near?450:231;
  const route=b.near?[[b.x-170,pavement],[b.x+244,pavement],[b.x+244,entrance.y],[entrance.x,entrance.y]]:
    [[b.x-170,pavement],[entrance.x,pavement],[entrance.x,entrance.y]];
  const lengths=route.slice(1).map((q,i)=>Math.hypot(q[0]-route[i][0],q[1]-route[i][1]));
  let distance=Math.max(0,Math.min(1,t))*lengths.reduce((sum,n)=>sum+n,0);
  for(let i=0;i<lengths.length;i++) {
    if(distance<=lengths[i]||i===lengths.length-1) {
      const f=distance/lengths[i];return {x:route[i][0]+(route[i+1][0]-route[i][0])*f,y:route[i][1]+(route[i+1][1]-route[i][1])*f};
    }
    distance-=lengths[i];
  }
}
function cityActors(buildings,time) {
  const count=buildings.length, population=cityPopulation(count), cars=[],people=[];
  const left=Math.min(...buildings.map(b=>b.x))-480, right=Math.max(...buildings.map(b=>b.x))+680;
  const duration=(right-left)/110, period=duration+18/count;
  for(let i=0;i<population.cars;i++) {
    const reverse=!!(i%2), phase=(time+(Math.floor(i/2)+(reverse?.43:0))*period/count)%period;
    if(phase>duration)continue;
    cars.push({x:reverse?right-phase*110:left+phase*110,y:reverse?374:308,reverse,variant:i%4});
  }
  for(let i=0;i<population.people;i++) {
    const target=buildings[i%count], phase=(time+i*12.7)%39;
    if(phase>21)continue;
    people.push({...cityWalk(target,phase/21),
      variant:i%4,stride:Math.sin(time*8+i)*2,target:target.number});
  }
  return {cars,people};
}
