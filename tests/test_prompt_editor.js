'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourceFile = path.join(__dirname, '../office_dashboard/static/js/panel/prompts.js');
const copy = value => JSON.parse(JSON.stringify(value));
const defaults = () => ({profile:'developer',subagent:'artel-worker',instructions:'',stages:{}});
function descriptor(extra = {}) {
  return {available:true, control:true, revision:1, values:defaults(), defaults:defaults(), overridden:false,
    alive:true, supported:true, applied:{revision:1}, max_text:6000,
    profiles:[{id:'developer',label:'Разработчик',description:'Реализация задач'}, {id:'tester',label:'Тестировщик',description:'Проверка и тестирование'}],
    stages:[{id:'generation',label:'Выполнение',description:'Основная работа'}, {id:'review',label:'Ревью',description:'Проверка результата'}],
    ...extra};
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; }
const response = (body, status = 200) => ({ok:status<400,status,json:async()=>copy(body)});
function harness({dataA=descriptor(),dataB=descriptor()}={}) {
  const elements=new Map(), listeners=new Map(), windows=new Map(), requests=[];
  const element=id=>{
    if(!elements.has(id)) elements.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,
      addEventListener:(name,handler)=>listeners.set(id+':'+name,handler)});
    return elements.get(id);
  };
  let handler=async(url,options)=>{
    if(options){const body=JSON.parse(options.body); if(body.action==='preview')return response({preview:{subagent:body.values.subagent,text:body.values.instructions}});
      return response(descriptor({revision:2,values:body.action==='reset'?defaults():body.values,overridden:body.action!=='reset'}));}
    if(url==='/api/prompts')return response({daemons:[{id:'a',name:'Альфа'},{id:'b',name:'Бета'}]});
    return response(url.endsWith('=a')?dataA:dataB);
  };
  const context=vm.createContext({Map,JSON,Date,URLSearchParams,$:element,lastSnapshot:{daemons:[]},
    esc:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;'),daemonOptionName:d=>d.id,
    fetch:(url,options)=>{requests.push({url,...(options?{body:JSON.parse(options.body)}:{})});return handler(url,options);},
    window:{addEventListener:(name,listener)=>windows.set(name,listener)}});
  vm.runInContext(fs.readFileSync(sourceFile,'utf8'),context);
  const run=code=>vm.runInContext(code,context);
  const fire=(id,type,value)=>{if(value!==undefined)element(id).value=value;return listeners.get(id+':'+type)({preventDefault(){}});};
  return {context,element,run,fire,requests,windows,setHandler:fn=>{handler=fn;},entry:()=>context.currentPrompt()};
}

test('role, global and per-stage drafts remain separate for each daemon across navigation', async()=>{
  const h=harness();await h.context.showPrompts('prompts');
  h.fire('promptProfile','input','tester');h.fire('promptInstructions','input','Проверяй все граничные условия');
  h.fire('promptStageInstructions','input','Добавь регрессионные тесты');
  h.fire('promptStage','change','review');h.fire('promptStageInstructions','input','Проверь flaky тесты');
  await h.fire('promptDaemon','change','b');
  assert.equal(h.element('promptProfile').value,'developer');
  h.fire('promptInstructions','input','Правила второго демона');
  await h.fire('promptDaemon','change','a');
  assert.equal(h.element('promptProfile').value,'tester');assert.equal(h.element('promptStage').value,'review');
  assert.equal(h.element('promptStageInstructions').value,'Проверь flaky тесты');
  h.fire('promptStage','change','generation');assert.equal(h.element('promptStageInstructions').value,'Добавь регрессионные тесты');
  assert.equal(h.entry().data.values.instructions,'');
  await h.context.showPrompts('office');await h.context.showPrompts('prompts');
  assert.equal(h.element('promptInstructions').value,'Проверяй все граничные условия');
  assert.equal(h.requests.filter(r=>r.url==='/api/prompts').length,1);
});
test('returning all fields to their original values clears dirty state', async()=>{
  const h=harness();await h.context.showPrompts('prompts');
  h.fire('promptInstructions','input','Temporary rule');h.fire('promptInstructions','input','');
  assert.equal(h.context.promptDirty(h.entry()),false);assert.equal(h.element('promptSave').disabled,true);
  h.fire('promptStageInstructions','input','Temporary stage');h.fire('promptStageInstructions','input','');
  assert.equal(h.context.promptDirty(h.entry()),false);
});
test('only the changed daemon is marked as a draft, including unloaded daemon options', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','Only Alpha');
  assert.equal(h.context.promptDirty(undefined),false);
  assert.match(h.element('promptDaemon').innerHTML,/<option value="a">[^<]*черновик/);
  assert.doesNotMatch(h.element('promptDaemon').innerHTML,/<option value="b">[^<]*черновик/);
});
test('dirty comparison ignores ordering and empty entries in the stage map', async()=>{
  const values={...defaults(),stages:{generation:'Generation',review:'Review'}};
  const h=harness({dataA:descriptor({values})});await h.context.showPrompts('prompts');
  h.entry().draft.stages={review:'Review',generation:'Generation'};
  assert.equal(h.context.promptDirty(h.entry()),false);
});
test('preview uses the selected daemon and unsaved stage without saving, and renders as plain text', async()=>{
  const h=harness();await h.context.showPrompts('prompts');
  h.fire('promptInstructions','input','<script>new instructions</script>');
  h.fire('promptStage','change','review');await h.context.promptPost('preview');
  const request=h.requests.at(-1).body;
  assert.equal(request.action,'preview');assert.equal(request.id,'a');assert.equal(request.stage,'review');
  assert.equal(request.values.instructions,'<script>new instructions</script>');
  assert.match(h.element('promptPreviewText').textContent,/<script>/);
  assert.equal(h.element('promptPreviewText').innerHTML,'');assert.equal(h.element('promptPreview').hidden,false);
  assert.equal(h.entry().data.revision,1);assert.equal(h.context.promptDirty(h.entry()),true);
  h.fire('promptInstructions','input','Changed again');assert.equal(h.element('promptPreview').hidden,true);
});
test('restore from config is a pending edit until explicit save, and can be discarded', async()=>{
  const saved=defaults();saved.instructions='Saved override';
  const h=harness({dataA:descriptor({values:saved,overridden:true})});await h.context.showPrompts('prompts');
  const count=h.requests.length;h.fire('promptDefaults','click');
  assert.equal(h.requests.length,count);assert.equal(h.entry().reset,true);assert.equal(h.context.promptDirty(h.entry()),true);
  h.fire('promptDiscard','click');assert.equal(h.entry().draft.instructions,'Saved override');assert.equal(h.entry().reset,false);
  h.fire('promptDefaults','click');await h.context.promptPost('reset');
  assert.equal(h.requests.at(-1).body.action,'reset');assert.equal(h.entry().reset,false);assert.equal(h.context.promptDirty(h.entry()),false);
  assert.equal(h.entry().data.overridden,false);
});
test('editing restored defaults becomes an explicit new override rather than discarding that edit', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptDefaults','click');
  h.fire('promptInstructions','input','Rule added after defaults');assert.equal(h.entry().reset,false);
  await h.context.promptPost('save');assert.equal(h.requests.at(-1).body.action,'save');
  assert.equal(h.entry().data.values.instructions,'Rule added after defaults');
});
test('a successful save updates its revision but keeps another daemon draft untouched', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','Alpha');
  await h.fire('promptDaemon','change','b');h.fire('promptInstructions','input','Beta');
  await h.fire('promptDaemon','change','a');await h.context.promptPost('save');
  assert.equal(h.entry().data.revision,2);assert.equal(h.context.promptDirty(h.entry()),false);
  assert.equal(h.requests.at(-1).body.revision,1);assert.equal(h.requests.at(-1).body.id,'a');
  await h.fire('promptDaemon','change','b');assert.equal(h.entry().draft.instructions,'Beta');assert.equal(h.context.promptDirty(h.entry()),true);
});
test('conflicts and failed previews retain unsaved edits and restore controls', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','Keep this draft');
  h.setHandler(async()=>response({error:'Настройки уже изменены в другом окне'},409));
  await h.context.promptPost('save');
  assert.equal(h.entry().draft.instructions,'Keep this draft');assert.equal(h.entry().data.revision,1);
  assert.equal(h.element('promptSave').disabled,false);assert.equal(h.element('promptDaemon').disabled,false);
  assert.match(h.element('promptSaveStatus').textContent,/не сохранены.*другом окне/);
  await h.context.promptPost('preview');
  assert.equal(h.entry().draft.instructions,'Keep this draft');assert.match(h.element('promptSaveStatus').textContent,/Предпросмотр недоступен/);
});
test('conflict reconciliation keeps the draft and stage, then requires an explicit save with the new revision', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','My draft');h.fire('promptStage','change','review');
  h.fire('promptStageInstructions','input','Check coverage');
  h.setHandler(async()=>response({error:'Настройки изменены в другой вкладке. Обновите данные перед сохранением.'},409));
  await h.context.promptPost('save');assert.equal(h.element('promptReload').disabled,false);
  assert.equal(h.element('promptReload').textContent,'Сверить с сервером');
  const writes=h.requests.filter(r=>r.body).length;
  h.setHandler(async()=>response(descriptor({revision:3,values:{...defaults(),instructions:'Changed on server'}})));
  await h.fire('promptReload','click');
  assert.equal(h.requests.filter(r=>r.body).length,writes,'reconciliation must never save implicitly');
  assert.equal(h.entry().draft.instructions,'My draft');assert.equal(h.entry().draft.stages.review,'Check coverage');
  assert.equal(h.entry().data.values.instructions,'Changed on server');assert.equal(h.entry().data.revision,3);
  assert.equal(h.element('promptStage').value,'review');assert.match(h.element('promptSaveStatus').textContent,/Черновик сохранён/);
  assert.equal(h.element('promptSave').disabled,false);
  h.setHandler(async(url,options)=>{const body=JSON.parse(options.body);return response(descriptor({revision:4,values:body.values}));});
  await h.context.promptPost('save');assert.equal(h.requests.at(-1).body.revision,3);
  assert.equal(h.requests.at(-1).body.values.instructions,'My draft');assert.equal(h.context.promptDirty(h.entry()),false);
});
test('failed conflict refresh leaves the draft visible and editable with retry available', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','My local draft');
  h.setHandler(async()=>response({error:'Настройки изменены в другой вкладке.'},409));await h.context.promptPost('save');
  h.setHandler(async()=>{throw Error('Network unavailable');});await h.fire('promptReload','click');
  assert.equal(h.entry().draft.instructions,'My local draft');assert.equal(h.element('promptForm').hidden,false);
  assert.equal(h.element('promptInstructions').disabled,false);assert.equal(h.element('promptReload').disabled,false);
  assert.match(h.element('promptLoadStatus').textContent,/Network unavailable/);
});
test('reconciling a pending reset uses new config defaults and still waits for explicit reset', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptDefaults','click');
  h.setHandler(async()=>response({error:'Настройки изменены в другой вкладке.'},409));await h.context.promptPost('reset');
  h.setHandler(async()=>response(descriptor({revision:3,defaults:{...defaults(),instructions:'New config defaults'}})));
  await h.fire('promptReload','click');assert.equal(h.entry().reset,true);
  assert.equal(h.entry().draft.instructions,'New config defaults');assert.equal(h.requests.at(-1).body,undefined);
});
test('in-flight mutations disable duplicate submission and switching until completion', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','Update');
  const pending=deferred();h.setHandler(()=>pending.promise);
  const save=h.context.promptPost('save');assert.equal(h.element('promptDaemon').disabled,true);assert.equal(h.element('promptStage').disabled,true);
  const count=h.requests.length;await h.context.promptPost('save');assert.equal(h.requests.length,count);
  pending.resolve(response(descriptor({values:{...defaults(),instructions:'Update'},revision:2})));await save;
  assert.equal(h.element('promptDaemon').disabled,false);assert.equal(h.element('promptStage').disabled,false);
});
test('a late fetch for the previous daemon cannot replace the current daemon', async()=>{
  const h=harness(),a=deferred(),b=deferred();h.setHandler(url=>url.endsWith('=a')?a.promise:b.promise);
  const first=h.context.promptLoad('a');const second=h.context.promptLoad('b');
  b.resolve(response(descriptor({values:{...defaults(),instructions:'Beta'}})));await second;
  a.resolve(response(descriptor({values:{...defaults(),instructions:'Alpha'}})));await first;
  assert.equal(h.run('promptEditor.id'),'b');assert.equal(h.element('promptInstructions').value,'Beta');assert.equal(h.element('promptDaemon').disabled,false);
});
test('returning to a cached daemon during an older load clears the loading lock', async()=>{
  const h=harness();await h.context.promptLoad('a');
  const pending=deferred();h.setHandler(()=>pending.promise);const load=h.context.promptLoad('b');
  await h.context.promptLoad('a');pending.resolve(response(descriptor()));await load;
  assert.equal(h.element('promptDaemon').disabled,false);assert.equal(h.element('promptReload').disabled,false);
});
test('failed initial catalog load is retryable and no daemon data is fabricated', async()=>{
  const h=harness();h.setHandler(async()=>{throw Error('offline');});await h.context.showPrompts('prompts');
  assert.match(h.element('promptLoadStatus').textContent,/offline/);assert.equal(h.element('promptReload').disabled,false);
  assert.equal(h.entry(),undefined);assert.equal(h.element('promptSave').disabled,true);
  h.setHandler(async url=>response(url==='/api/prompts'?{daemons:[{id:'a'}]}:descriptor()));await h.fire('promptReload','click');
  assert.equal(h.element('promptForm').hidden,false);assert.equal(h.element('promptLoadStatus').textContent,'');
});
test('demo permits preview but submit cannot write and unsaved demo changes do not block exit', async()=>{
  const h=harness({dataA:descriptor({control:false})});await h.context.showPrompts('prompts');
  h.fire('promptInstructions','input','Try the tester role');assert.equal(h.element('promptSave').disabled,true);
  const count=h.requests.length;h.fire('promptForm','submit');assert.equal(h.requests.length,count);
  await h.context.promptPost('preview');assert.equal(h.requests.at(-1).body.action,'preview');
  let blocked=false;h.windows.get('beforeunload')({preventDefault(){blocked=true;}});assert.equal(blocked,false);
});
test('SSE applied status updates without replacing edited fields, and exit protects writable drafts', async()=>{
  const h=harness();await h.context.showPrompts('prompts');h.fire('promptInstructions','input','Keep draft');
  h.context.syncPromptStatus({daemons:[{id:'a',alive:true,features:['prompt-control'],prompt_control:{revision:0}}]});
  assert.match(h.element('promptApplied').textContent,/после текущей работы/);
  h.context.syncPromptStatus({daemons:[{id:'a',alive:true,features:['prompt-control'],prompt_control:{revision:1}}]});
  assert.match(h.element('promptApplied').textContent,/применены/);assert.equal(h.entry().draft.instructions,'Keep draft');
  let blocked=false;h.windows.get('beforeunload')({preventDefault(){blocked=true;}});assert.equal(blocked,true);
  h.fire('promptDiscard','click');blocked=false;h.windows.get('beforeunload')({preventDefault(){blocked=true;}});assert.equal(blocked,false);
});
