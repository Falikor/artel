'use strict';
// No browser dependency: exercise the actual boot and scene admission boundaries with failed I/O.
const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const source = fs.readFileSync(path.join(root,'office_dashboard/static/js/core/data.js'),'utf8');
function harness(options = {}) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id,{id,hidden:false,textContent:'',setAttribute(){},before(){},querySelector(){return element(id+'-text');}});
    return elements.get(id);
  };
  element('stats').hidden = true;
  const calls = {input:0,frames:0,legend:0,roster:0,cards:0,sync:0,sources:[]};
  const context = vm.createContext({
    console:{warn(){},error(){}},setTimeout,clearTimeout,AbortController,Promise,Map,Set,Number,Date,
    $:element,document:{createElement:()=>element('created')},window:{addEventListener(){}},
    office:{plate:null,props:null,doors:[],decor:{},chars:{},thumbs:{}},cabinet:{},drawer:{id:null},clockSkew:0,
    buildLegend:()=>calls.legend++,resize(){},setupInput:()=>calls.input++,loop(){},requestAnimationFrame:()=>calls.frames++,
    EventSource:class {constructor(url){this.url=url;calls.sources.push(this);}},
    fetch:options.fetch || (async()=>({ok:true,json:async()=>options.assets || {plate:'plate',characters:[]}})),
    loadImage:options.loadImage || (async src=>({src,width:128,height:128})),
    buildCharacter:definition=>({id:definition.id,anims:{idle_down:{cells:[{row:0,col:0}],dur:[100],total:100}}}),
    charThumb:character=>'thumb:'+character.id,
    buildSheet:()=>({anims:{}}),addLoungeAnims(){},buildCat:()=>({}),Cat:class{},
    syncOffice:()=>calls.sync++,renderBuilding:()=>calls.roster++,renderCards:()=>calls.cards++,renderCharPicker(){},refreshDrawer(){},
    quality:{},renderStats(){},
  });
  vm.runInContext(source,context,{filename:'data.js'});
  return {context,calls,element};
}
test('asset manifest failure does not block SSE, keyboard setup or live roster',async()=>{
  const {context,calls,element}=harness({fetch:async()=>{throw Error('network failure');}});
  const pending=context.boot();
  assert.equal(calls.input,1);assert.equal(calls.sources.length,1);assert.equal(calls.frames,1);
  await pending;
  calls.sources[0].onmessage({data:JSON.stringify({daemons:[{id:'demo'}],offices:[],demo:false})});
  assert.equal(calls.roster,1);assert.equal(calls.cards,1);
  assert.equal(element('sceneAssetStatus').hidden,false);
  assert.match(element('sceneAssetStatus').textContent,/Статусы, логи и управление доступны/);
});
test('controls connect before a slow image resolves, and receive states while artwork is pending',async()=>{
  let resolveImage;
  const blocked=new Promise(resolve=>{resolveImage=resolve;});
  const {context,calls,element}=harness({assets:{plate:'slow',characters:[{id:'good',atlas:'character'}]},loadImage:src=>src==='slow'?blocked:Promise.resolve({width:128,height:128})});
  const pending=context.boot();
  assert.equal(calls.input,1);assert.equal(calls.sources.length,1);
  calls.sources[0].onmessage({data:JSON.stringify({daemons:[],offices:[]})});
  assert.equal(calls.cards,1);
  resolveImage({width:1254,height:1254});await pending;
  assert.ok(context.office.plate);assert.ok(context.office.chars.good);
  assert.equal(element('sceneAssetStatus').hidden,true);
  assert.equal(calls.sources.length,1);
});
test('one bad character and office sheet do not remove successful artwork or stop data',async()=>{
  const {context,calls,element}=harness({
    assets:{plate:'broken-plate',office:{atlas:'broken-office'},characters:[{id:'bad',atlas:'broken-character'},{id:'good',atlas:'good'}]},
    loadImage:async src=>{if(src.startsWith('broken'))throw Error('missing');return {width:128,height:128};},
  });
  await context.boot();
  assert.equal(context.office.plate,null);assert.equal(context.office.props,null);
  assert.equal(context.office.chars.bad,undefined);assert.ok(context.office.chars.good);
  assert.equal(context.office.thumbs.good,'thumb:good');assert.equal(calls.sync,1);
  assert.match(element('sceneAssetStatus').textContent,/фон офиса/);
  assert.match(element('sceneAssetStatus').textContent,/персонажи/);
  calls.sources[0].onmessage({data:JSON.stringify({daemons:[],offices:[]})});
  assert.equal(calls.cards,2);
});
test('empty animations are removed, and a character without fallback pose is rejected',()=>{
  const {context}=harness();
  assert.throws(()=>context.usableCharacter({anims:{idle_down:{cells:[],dur:[],total:1}}}),/базовой анимации/);
  const character=context.usableCharacter({anims:{idle_down:{cells:[{}],dur:[100],total:100},walk:{cells:[],dur:[],total:1}}});
  assert.equal(character.anims.walk,undefined);assert.ok(character.anims.idle_down);
});
test('syncOffice admits workers only after both plate and a usable character exist',()=>{
  const building=fs.readFileSync(path.join(root,'office_dashboard/static/js/office/building.js'),'utf8');
  const sync=building.slice(building.indexOf('function syncOffice()'),building.indexOf("$('backBuilding')"));
  const daemon={id:'demo',office_slot:0},office={plate:null,workers:new Map(),reserved:new Map(),spots:new Set(),doors:[],t:0};
  let character,created=0,destroyed=0,ingested=0;
  const context=vm.createContext({
    office,buildingView:{room:'room',rendered:'room'},timers:[],cabinet:{},visibleDaemons:()=>[daemon],charFor:()=>character,
    Worker:class{constructor(d,slot){assert.ok(character);this.slot=slot;created++;}ingest(){ingested++;}destroy(){destroyed++;}},
  });
  vm.runInContext(sync,context);
  context.syncOffice();assert.equal(created,0);
  office.plate={};context.syncOffice();assert.equal(created,0);
  character={anims:{idle_down:{}}};context.syncOffice();assert.equal(created,1);assert.equal(office.workers.size,1);
  context.syncOffice();assert.equal(created,1);assert.equal(ingested,2);
  character=undefined;context.syncOffice();assert.equal(destroyed,1);assert.equal(office.workers.size,0);
});
