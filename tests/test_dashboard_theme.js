'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../office_dashboard/static/js/core/theme.js'),'utf8');
function run(saved, dark=false, denied=false) {
  const listeners={}, select={value:null,addEventListener:(name,fn)=>listeners[name]=fn};
  const favicon={href:'/static/favicon.svg',getAttribute(name){return this[name];},setAttribute(name,value){this[name]=value;}};
  const document={documentElement:{dataset:{}},getElementById:id=>({themeSelect:select,themeFavicon:favicon})[id],addEventListener:(name,fn)=>listeners[name]=fn};
  const media={matches:dark,addEventListener:(name,fn)=>listeners.media=fn};
  const writes=[];
  vm.runInNewContext(source,{document,window:{matchMedia:()=>media,addEventListener:(name,fn)=>listeners[name]=fn},localStorage:{getItem(){if(denied)throw Error('denied');return saved;},setItem(k,v){if(denied)throw Error('denied');writes.push([k,v]);}}});
  listeners.DOMContentLoaded();
  return {document,select,media,listeners,writes,favicon,theme:()=>document.documentElement.dataset.theme};
}
test('system follows OS changes, explicit preference survives them',()=>{
  const s=run(null,true);assert.equal(s.theme(),'dark');assert.equal(s.select.value,'system');
  s.media.matches=false;s.listeners.media();assert.equal(s.theme(),'light');
  s.listeners.change({target:{value:'dark'}});assert.equal(s.theme(),'dark');
  s.listeners.media();assert.equal(s.theme(),'dark');assert.deepEqual(s.writes,[['artel-theme','dark']]);
  assert.equal(run('dark',false).theme(),'dark');
});
test('invalid values and blocked storage do not prevent initial rendering or switching',()=>{
  assert.equal(run('invalid',true).theme(),'dark');
  const s=run(null,false,true);assert.equal(s.theme(),'light');
  s.listeners.change({target:{value:'dark'}});assert.equal(s.theme(),'dark');
});
test('other tabs and clearing storage synchronize the setting',()=>{
  const s=run('light',true);
  s.listeners.storage({key:'artel-theme',newValue:'dark'});assert.equal(s.theme(),'dark');assert.equal(s.select.value,'dark');
  s.listeners.storage({key:null,newValue:null});assert.equal(s.select.value,'system');assert.equal(s.theme(),'dark');
});
test('favicon follows the selected theme immediately, independently from the OS',()=>{
  const s=run('light',true);
  assert.equal(s.favicon.href,'/static/favicon-light.svg');
  s.listeners.change({target:{value:'dark'}});
  assert.equal(s.favicon.href,'/static/favicon-dark.svg');
  s.media.matches=false;s.listeners.media();
  assert.equal(s.favicon.href,'/static/favicon-dark.svg');
  s.listeners.change({target:{value:'system'}});
  assert.equal(s.favicon.href,'/static/favicon-light.svg');
  s.media.matches=true;s.listeners.media();
  assert.equal(s.favicon.href,'/static/favicon-dark.svg');
  assert.equal(run('dark',false).favicon.href,'/static/favicon-dark.svg');
  s.listeners.storage({key:'artel-theme',newValue:'light'});
  assert.equal(s.favicon.href,'/static/favicon-light.svg');
  s.listeners.storage({key:null,newValue:null});
  assert.equal(s.favicon.href,'/static/favicon-dark.svg');
});
test('local favicon assets preserve the mark and match the interface palette',()=>{
  const staticDir=path.join(__dirname,'../office_dashboard/static');
  const light=fs.readFileSync(path.join(staticDir,'favicon-light.svg'),'utf8');
  const dark=fs.readFileSync(path.join(staticDir,'favicon-dark.svg'),'utf8');
  assert.deepEqual([...light.matchAll(/ d="([^"]+)"/g)].map(m=>m[1]),[...dark.matchAll(/ d="([^"]+)"/g)].map(m=>m[1]));
  assert.match(light,/fill="#087f73"/);
  assert.match(dark,/fill="#77d4c2"/);
  assert.match(fs.readFileSync(path.join(staticDir,'index.html'),'utf8'),/id="themeFavicon" rel="icon"/);
});
