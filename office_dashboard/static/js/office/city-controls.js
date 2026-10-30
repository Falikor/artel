'use strict';
/* Camera navigation uses CSS pixels, independently of canvas resolution. */
function cityBaseCamera() {
  const buildings=city.buildings.length?city.buildings:[{number:1,x:0,y:0,near:false,rooms:[],floors:1}];
  return cityCamera(city.width,city.height,buildings,city.scenery,city.focus);
}
function cityUpdateZoomControls() {
  const zoom=city.view.zoom;
  $('cityZoomValue').textContent=`${Math.round(zoom*100)}%`;
  $('cityZoomIn').disabled=zoom>=CITY_ZOOM_MAX-1e-6;
  $('cityZoomOut').disabled=zoom<=CITY_ZOOM_MIN+1e-6;
}
function citySetView(view,fromGesture=false) {
  if(!fromGesture)city.cancelGesture?.();
  city.view=cityClampView(cityBaseCamera(),view);
  city.closeUntil=performance.now()+350;
  city.dirty=true;
  cityUpdateZoomControls();
}
function cityResetView() {
  city.cancelGesture?.();
  city.view={zoom:1,x:0,y:0};city.dirty=true;
  cityUpdateZoomControls();
}
function cityZoomBy(factor,point) {
  citySetView(cityZoomAt(cityBaseCamera(),city.view,city.view.zoom*factor,point));
}
function cityFitDistrict() {
  city.focus=null;citySelect(null);cityResetView();renderCityBuildings();
}
function cityIgnoreClick(e) {
  return e.detail!==0 && performance.now()<city.suppressClickUntil;
}
function initCityControls() {
  const viewport=$('cityViewport'), canvas=city.canvas, pointers=new Map();
  let gesture=null, moved=false;
  const point=e=>{const r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top];};
  const pair=()=>[...pointers.values()].slice(0,2);
  const center=ps=>ps.length===1?ps[0]:[(ps[0][0]+ps[1][0])/2,(ps[0][1]+ps[1][1])/2];
  const rebase=()=>{
    const ps=pair();
    gesture=ps.length?{center:center(ps),distance:ps.length>1?Math.max(1,Math.hypot(ps[1][0]-ps[0][0],ps[1][1]-ps[0][1])):0,view:{...city.view}}:null;
  };
  const stop=()=>{
    const ids=[...pointers.keys()];pointers.clear();gesture=null;
    city.dragging=false;viewport.classList.remove('is-dragging');canvas.style.cursor='';
    for(const id of ids)if(canvas.hasPointerCapture(id))canvas.releasePointerCapture(id);
  };
  city.cancelGesture=()=>{
    if(pointers.size)city.suppressClickUntil=performance.now()+400;
    stop();
  };
  viewport.addEventListener('pointerdown',e=>{
    if(e.button!==0 || (e.pointerType!=='touch' && pointers.size))return;
    if(!pointers.size){moved=false;city.pointerLabel=e.target.closest('[data-city-building]')?.dataset.cityBuilding || null;}
    pointers.set(e.pointerId,point(e));
    if(pointers.size>1){moved=true;city.pointerLabel=null;}
    city.dragging=true;city.closeUntil=performance.now()+350;
    canvas.setPointerCapture(e.pointerId);rebase();
    if(e.pointerType==='mouse' && e.target===canvas)canvas.focus({preventScroll:true});
  });
  viewport.addEventListener('pointermove',e=>{
    if(!pointers.has(e.pointerId))return;
    pointers.set(e.pointerId,point(e));
    const ps=pair(), mid=center(ps), dx=mid[0]-gesture.center[0],dy=mid[1]-gesture.center[1];
    if(!moved && Math.hypot(dx,dy)<6)return;
    moved=true;viewport.classList.add('is-dragging');canvas.style.cursor='grabbing';
    const base=cityBaseCamera();
    const desiredZoom=ps.length>1?gesture.view.zoom*Math.hypot(ps[1][0]-ps[0][0],ps[1][1]-ps[0][1])/gesture.distance:gesture.view.zoom;
    const view=ps.length>1?cityZoomAt(base,gesture.view,desiredZoom,gesture.center):gesture.view;
    const requested={...view,x:view.x+dx,y:view.y+dy};
    citySetView(requested,true);
    // At an edge, reverse immediately instead of requiring the user to undo
    // an invisible overshoot before the camera starts following again.
    if(Math.abs(desiredZoom-city.view.zoom)>1e-6 || Math.abs(requested.x-city.view.x)>1e-6 || Math.abs(requested.y-city.view.y)>1e-6)rebase();
  });
  const finish=e=>{
    if(!pointers.has(e.pointerId))return;
    pointers.delete(e.pointerId);
    if(moved || e.type==='pointercancel')city.suppressClickUntil=performance.now()+400;
    if(!pointers.size && !moved && e.type!=='pointercancel' && city.pointerLabel){
      const value=city.pointerLabel;
      cityFocusClick({detail:0,target:{closest:()=>({dataset:{cityBuilding:value}})}});
      city.suppressClickUntil=performance.now()+400;
    }
    if(e.type==='pointercancel' || !pointers.size)stop();else rebase();
    if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);
  };
  viewport.addEventListener('pointerup',finish);
  viewport.addEventListener('pointercancel',finish);
  canvas.addEventListener('lostpointercapture',e=>{
    if(pointers.has(e.pointerId)){city.suppressClickUntil=performance.now()+400;stop();}
  });
  window.addEventListener('blur',city.cancelGesture);
  viewport.addEventListener('wheel',e=>{
    e.preventDefault();
    if(pointers.size || !e.deltaY)return;
    const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?city.height:1);
    cityZoomBy(Math.exp(-Math.max(-240,Math.min(240,delta))*(e.ctrlKey?.008:.002)),point(e));
  },{passive:false});
  canvas.addEventListener('keydown',e=>{
    if(e.ctrlKey || e.metaKey || e.altKey)return;
    if(['+','=','-','_','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home'].includes(e.key))e.preventDefault();else return;
    if(e.key==='Home')cityFitDistrict();
    else if(['+','=','-','_'].includes(e.key))cityZoomBy(['+','='].includes(e.key)?1.35:1/1.35);
    else citySetView({...city.view,x:city.view.x+(e.key==='ArrowLeft'?70:e.key==='ArrowRight'?-70:0),y:city.view.y+(e.key==='ArrowUp'?70:e.key==='ArrowDown'?-70:0)});
  });
  $('cityZoomIn').addEventListener('click',()=>cityZoomBy(1.35));
  $('cityZoomOut').addEventListener('click',()=>cityZoomBy(1/1.35));
  $('cityReset').addEventListener('click',cityFitDistrict);
  cityUpdateZoomControls();
}
