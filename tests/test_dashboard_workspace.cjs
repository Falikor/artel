const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const listeners = {};
let editorOpen = true;
const container = {dataset:{source:'s1',entry:'e1'}, _text:'', set textContent(v){this._text=v;editorOpen=false;}, get textContent(){return this._text;}};
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {value:id==='workspaceDays'?'30':'',disabled:false,textContent:'',
    addEventListener(type,handler){listeners[id+':'+type]=handler;},setAttribute(){},
    querySelectorAll(selector){return selector==='[data-source][data-entry]' ? [container] : [];}});
  return elements.get(id);
}
const context = vm.createContext({URLSearchParams, Date, setInterval,clearInterval,setTimeout,clearTimeout,
  $:element, esc:String, document:{querySelector(){return editorOpen ? {} : null;}},
  fetch:async(url,options)=>({ok:!!options,status:options?200:503,json:async()=>options?{ok:true}:{error:'Connection lost'}})});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../office_dashboard/static/js/stats/workspace.js'),'utf8'),context);
(async()=>{
  let prevented = false;
  await listeners['workspaceBody:submit']({target:{matches:()=>true,closest:()=>null},preventDefault(){prevented=true;}});
  assert.strictEqual(prevented,false,'requirements form must not be captured by memory submit handler');
  vm.runInContext("workspace.view='memory'; workspace.data={};",context);
  await vm.runInContext("memoryAction('s1','e1','approve')",context);
  assert.strictEqual(editorOpen,false,'successful POST closes editor even if refresh fails');
  assert.strictEqual(element('workspaceRefresh').disabled,false,'refresh stays available after failed GET');
  assert.match(element('workspaceStatus').textContent,/Решение сохранено/);
  assert.match(element('workspaceStatus').textContent,/Connection lost/);
  assert.match(element('workspaceStatus').textContent,/Обновить/);
  console.log('PASS: submit ownership and saved-write/failed-refresh recovery');
})().catch(error=>{console.error(error);process.exitCode=1;});
