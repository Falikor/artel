'use strict';
// Run: node tests/test_office_social.js
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('office_dashboard/static/js/office/social.js','utf8');
const d={id:'a',office_id:'one',stage:'idle',alive:true};
const preferences=new Map(), classes=new Set();
const reduced={matches:false,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}};
const motionButton={listeners:{},attributes:{},addEventListener(type,fn){this.listeners[type]=fn;},
 setAttribute(name,value){this.attributes[name]=value;}};
const context={window:{matchMedia:()=>reduced},Date,Math,ACTIVITIES:{},ACTIVITY_WEIGHTS:{},
 storage:{get:(key,fallback)=>preferences.has(key)?preferences.get(key):fallback,
  set:(key,value)=>preferences.set(key,value)},
 $:id=>id==='motionToggle'?motionButton:null,
 lastSnapshot:{daemons:[d,{id:'b',office_id:'two',stage:'idle',alive:true}],offices:[{id:'one'},{id:'two'}]},
 office:{workers:new Map(),plate:true,t:1},buildingView:{room:'one'},
 document:{hidden:false,body:{classList:{contains:name=>classes.has(name),
  toggle(name,force){if(force)classes.add(name);else classes.delete(name);return force;}}}},
 syncOffice(){},renderBuilding(){},renderCards(){},pick:a=>a[0]};
vm.createContext(context);vm.runInContext(source,context);
assert.equal(vm.runInContext("startOfficeVisit('a','two')",context),true);
assert.equal(vm.runInContext("startOfficeVisit('a','two')",context),false);
vm.runInContext('social.nextVisit=Infinity; socialTick(Date.now())',context);
assert.equal(vm.runInContext('socialRoom(lastSnapshot.daemons[0])',context),'two');
assert.equal(d.office_id,'one','visits must never change assignments');
d.stage='generating';vm.runInContext('social.nextTick=0; socialTick(Date.now())',context);
assert.equal(vm.runInContext('socialRoom(lastSnapshot.daemons[0])',context),'one');
assert.equal(vm.runInContext('social.visits.size',context),0,'work cancels visits');
d.stage='idle';vm.runInContext("startOfficeVisit('a','two'); social.nextTick=0; socialTick(Date.now())",context);
vm.runInContext("social.visits.get('a').at=Date.now()-46000; social.nextTick=0; socialTick(Date.now()); social.nextTick=0; socialTick(Date.now())",context);
assert.equal(vm.runInContext('social.visits.size',context),0,'visitors return home');
const reward=vm.runInContext("reactionOffset({feedback:{at:0,kind:'praise'}},1)",context);
const reprimand=vm.runInContext("reactionOffset({feedback:{at:0,kind:'reprimand'}},1)",context);
assert.notDeepEqual([...reward],[...reprimand]);
vm.runInContext('social.reduced.matches=true',context);
assert.deepEqual([...vm.runInContext("reactionOffset({feedback:{at:0,kind:'praise'}},1)",context)],[0,0]);
console.log('Office visits, cancellation, return and distinct/reduced reactions: OK');
