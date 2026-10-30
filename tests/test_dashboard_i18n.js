'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const staticPath=path.join(__dirname,'../office_dashboard/static');
const source=fs.readFileSync(path.join(staticPath,'js/core/i18n.js'),'utf8');
function element(text='',attributes={}) {
  return {textContent:text,attributes:{...attributes},getAttribute(k){return this.attributes[k]??null;},setAttribute(k,v){this.attributes[k]=v;}};
}
function run({saved=null,denied=false,confirm=true,promptEntries=[]}={}) {
  const listeners={},selectListeners={},writes=[],confirmations=[],alerts=[];
  const label=element('Статистика',{'data-i18n-en':'Statistics'});
  const title=element('Артель — рабочее пространство',{'data-i18n-en':'Artel — workspace'});
  const userData=element('Офис команды — пользовательский текст');
  const changedLabel=element('Resume scene',{'data-i18n-en':'Pause scene'});
  const search=element('',{'aria-label':'Найти демона','data-i18n-aria-label':'Find a daemon','placeholder':'Поиск','data-i18n-placeholder':'Search'});
  const meta=element('',{content:'Рабочее пространство','data-i18n-content':'Workspace'});
  const tooltip=element('',{title:'Приблизить','data-i18n-title':'Zoom in'});
  const nodes=[label,title,userData,changedLabel,search,meta,tooltip];
  const select={value:null,addEventListener(k,v){selectListeners[k]=v;}};
  const document={documentElement:{},getElementById(id){return id==='languageSelect'?select:null;},querySelectorAll(selector){const attr=selector.slice(1,-1);return nodes.filter(n=>n.attributes[attr]!=null);},addEventListener(k,v){(listeners[k]??=[]).push(v);}};
  const window={confirm(text){confirmations.push(text);return confirm;},alert(text){alerts.push(text);},location:{reload(){state.reloads++;}}};
  const context={document,window,localStorage:{getItem(){if(denied)throw Error('denied');return saved;},setItem(k,v){if(denied)throw Error('denied');writes.push([k,v]);}},promptEditor:{entries:new Map(promptEntries)},promptDirty:entry=>entry.dirty};
  const state={document,window,label,title,userData,changedLabel,search,meta,tooltip,select,writes,confirmations,alerts,reloads:0,context,
    emit(name,target){for(const listener of listeners[name]||[])listener({target});},
    change(value){select.value=value;selectListeners.change({target:select});}};
  vm.createContext(context);vm.runInContext(source,context);state.emit('DOMContentLoaded');return state;
}
function formField({value='initial',id='description',formId='editor',type='text',outside=false}={}) {
  const form={id:formId,matches:selector=>selector==='form',closest:()=>null};
  const field={id,value,type,defaultValue:value,tagName:'INPUT',isConnected:true,disabled:false,readOnly:false,
    matches:selector=>selector==='input, select, textarea',closest:selector=>outside?null:(selector==='form'||selector==='#'+formId?form:null)};
  return {form,field};
}
test('English is saved per browser and exposed before other scripts',()=>{
  const s=run({saved:'en'});
  assert.equal(s.document.documentElement.lang,'en');assert.equal(s.select.value,'en');
  assert.equal(s.context.tr('Команда','Team'),'Team');assert.equal(s.context.uiLocale(),'en-US');
  assert.equal(s.label.textContent,'Statistics');assert.equal(s.title.textContent,'Artel — workspace');
  assert.equal(s.search.attributes['aria-label'],'Find a daemon');assert.equal(s.search.attributes.placeholder,'Search');
  assert.equal(s.meta.attributes.content,'Workspace');assert.equal(s.tooltip.attributes.title,'Zoom in');
  assert.equal(s.userData.textContent,'Офис команды — пользовательский текст');
  assert.equal(s.changedLabel.textContent,'Resume scene');
});
test('Russian remains the default and invalid preferences do not affect rendering',()=>{
  for(const saved of [null,'ru','unknown']) {
    const s=run({saved});assert.equal(s.document.documentElement.lang,'ru');assert.equal(s.label.textContent,'Статистика');
    assert.equal(s.context.tr('Команда','Team'),'Команда');assert.equal(s.context.uiLocale(),'ru-RU');
  }
});
test('language change persists then reloads, same language is a no-op',()=>{
  const s=run();s.change('ru');assert.equal(s.reloads,0);
  s.change('en');assert.deepEqual(s.writes,[['artel-language','en']]);assert.equal(s.reloads,1);
  assert.equal(s.window.artelLanguageReloadApproved,true);assert.equal(s.confirmations.length,0);
});
test('storage denial keeps the current language instead of a misleading reload',()=>{
  const s=run({denied:true});assert.equal(s.context.uiLocale(),'ru-RU');s.change('en');
  assert.equal(s.reloads,0);assert.equal(s.select.value,'ru');assert.equal(s.alerts.length,1);
});
test('edited forms require confirmation; cancel preserves edits and preference',()=>{
  const s=run({confirm:false}),{field}=formField();s.emit('focusin',field);field.value='draft';s.emit('input',field);s.change('en');
  assert.equal(s.confirmations.length,1);assert.equal(s.reloads,0);assert.deepEqual(s.writes,[]);assert.equal(s.select.value,'ru');assert.equal(field.value,'draft');
});
test('confirmed locale change reloads despite drafts, with one confirmation flag',()=>{
  const s=run({saved:'en'}),{field}=formField();s.emit('focusin',field);field.value='draft';s.change('ru');
  assert.equal(s.confirmations.length,1);assert.match(s.confirmations[0],/Unsaved changes/);
  assert.equal(s.reloads,1);assert.equal(s.window.artelLanguageReloadApproved,true);
});
test('filters, reverted values, detached editors, and saved forms do not warn',()=>{
  for(const kind of ['filter','reverted','detached','saved']) {
    const s=run(),{field,form}=formField({outside:kind==='filter'});s.emit('focusin',field);field.value='draft';s.emit('input',field);
    if(kind==='reverted')field.value='initial';
    if(kind==='detached')field.isConnected=false;
    if(kind==='saved')s.context.markFormClean(form);
    s.change('en');assert.equal(s.confirmations.length,0,kind);assert.equal(s.reloads,1,kind);
  }
});
test('drafts retained by inactive workspace tabs remain protected',()=>{
  const s=run({confirm:false}),{field}=formField();s.emit('focusin',field);field.value='draft';s.emit('input',field);
  field.isConnected=false;s.context.workspace={cache:{requirements:{nodes:[{contains:n=>n===field}]}}};
  s.change('en');assert.equal(s.confirmations.length,1);assert.equal(s.reloads,0);
  delete s.context.workspace.cache.requirements;
  assert.equal(s.context.languageHasUnsavedChanges(),false);
});
test('saved field becomes the baseline for subsequent edits without refocus',()=>{
  const s=run(),{field,form}=formField();s.emit('focusin',field);field.value='saved value';s.emit('input',field);s.context.markFormClean(form);
  field.value='another draft';s.emit('input',field);assert.equal(s.context.languageHasUnsavedChanges(),true);
  field.value='saved value';s.emit('input',field);assert.equal(s.context.languageHasUnsavedChanges(),false);
});
test('dirty prompt drafts for any daemon are protected, including preview-only mode',()=>{
  const s=run({confirm:false,promptEntries:[['other-daemon',{dirty:true,data:{control:false}}]]});s.change('en');
  assert.equal(s.confirmations.length,1);assert.equal(s.reloads,0);
});
test('clean prompt editor ignores programmatic field values and stage switching',()=>{
  const s=run({promptEntries:[['daemon',{dirty:false}]]}),{field}=formField({formId:'promptForm'});
  s.emit('focusin',field);field.value='loaded from another stage';s.emit('input',field);s.change('en');
  assert.equal(s.confirmations.length,0);assert.equal(s.reloads,1);
});
test('autofill edits without focus are protected',()=>{
  const s=run({confirm:false}),{field}=formField();field.value='autofilled draft';s.emit('input',field);s.change('en');
  assert.equal(s.confirmations.length,1);assert.equal(s.reloads,0);
});
test('known server UI messages translate exactly; unknown text and data pass through',()=>{
  const s=run({saved:'en'});s.context.registerServerMessages({'Сохранено':'Saved'});
  assert.equal(s.context.translateServerMessage('Сохранено'),'Saved');
  assert.equal(s.context.translateServerMessage('Сохранено моё описание'),'Сохранено моё описание');
  assert.equal(s.context.translateServerMessage(null),null);
  const ru=run();ru.context.registerServerMessages({'Сохранено':'Saved'});assert.equal(ru.context.translateServerMessage('Сохранено'),'Сохранено');
});
test('language selector is beside theme; bootstrap precedes every application script',()=>{
  const html=fs.readFileSync(path.join(staticPath,'index.html'),'utf8');
  assert.ok(html.indexOf('/js/core/i18n.js')<html.indexOf('/js/core/theme.js'));
  assert.match(html,/<div class="ui-preferences"><select id="languageSelect"[\s\S]*?<\/select><select id="themeSelect"/);
  assert.match(html,/<option value="ru" lang="ru">Русский<\/option><option value="en" lang="en">English<\/option>/);
  assert.match(html,/<title data-i18n-en="Artel — workspace">/);
  assert.match(html,/data-i18n-content="A workspace for autonomous development/);
  assert.doesNotMatch(source,/MutationObserver|innerHTML\s*=/);
});
