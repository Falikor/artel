'use strict';
/* Drafts belong to individual daemons; navigation and refresh never overwrite edits. */
const promptEditor = {visible:false, id:'', entries:new Map(), catalog:[], serial:0, loading:false, busy:false};
const clonePrompt = value => JSON.parse(JSON.stringify(value));
function currentPrompt() { return promptEditor.entries.get(promptEditor.id); }
function comparablePrompt(values) { return JSON.stringify([values.profile,values.subagent,values.instructions,Object.entries(values.stages||{}).filter(([,text])=>text).sort(([a],[b])=>a.localeCompare(b))]); }
function promptDirty(entry) { return !!entry && (entry.reset || comparablePrompt(entry.draft)!==comparablePrompt(entry.data.values)); }
function promptName(row) {
  const resident=(lastSnapshot.daemons||[]).find(d=>d.id===row.id);
  return resident ? daemonOptionName(resident) : [row.name||row.id,row.project].filter(Boolean).join(' · ');
}
function promptOptions() {
  const select=$('promptDaemon');
  select.innerHTML=promptEditor.catalog.map(row=>`<option value="${esc(row.id)}">${esc(promptName(row))}${promptDirty(promptEditor.entries.get(row.id))?' · черновик':''}</option>`).join('');
  select.value=promptEditor.id;
}
function promptControls() {
  const entry=currentPrompt(), dirty=promptDirty(entry), busy=promptEditor.busy;
  $('promptDaemon').disabled=busy||promptEditor.loading;
  $('promptReload').disabled=busy||promptEditor.loading||(dirty&&!entry?.conflict);
  $('promptReload').textContent=entry?.conflict?'Сверить с сервером':'Обновить';
  ['promptProfile','promptSubagent','promptInstructions','promptStage','promptStageInstructions','promptDefaults','promptPreviewButton'].forEach(id=>$(id).disabled=busy||!entry);
  $('promptDiscard').disabled=busy||!dirty;
  $('promptSave').disabled=busy||!dirty||!entry?.data.control;
}
function promptApplied(entry) {
  const data=entry.data;
  if(!data.control) return 'Режим просмотра: можно проверить инструкции, сохранение отключено.';
  if(!data.alive) return 'Настройки применятся при следующем запуске демона.';
  if(!data.supported) return 'Чтобы применять настройки, перезапустите демона с обновлённым кодом.';
  if(data.applied?.revision!==data.revision) return 'Демон применит сохранённые настройки после текущей работы.';
  return 'Сохранённые настройки применены демоном.';
}
function syncPromptStatus(snapshot) {
  for(const row of snapshot.daemons||[]) {
    const entry=promptEditor.entries.get(row.id);if(!entry)continue;
    entry.data.applied=row.prompt_control||null;
    entry.data.alive=!!row.alive;
    entry.data.supported=(row.features||[]).includes('prompt-control');
  }
  if(promptEditor.visible&&currentPrompt())$('promptApplied').textContent=promptApplied(currentPrompt());
}
function promptStageRender() {
  const entry=currentPrompt(); if(!entry)return;
  const stage=entry.data.stages.find(s=>s.id===entry.stage);
  $('promptStage').value=entry.stage;
  $('promptStageHint').textContent=stage?.description||'';
  $('promptStageInstructions').value=entry.draft.stages[entry.stage]||'';
  $('promptStageCount').textContent=`${$('promptStageInstructions').value.length.toLocaleString('ru-RU')} / ${entry.data.max_text||6000} символов · пустое поле сохраняет стандартное поведение этапа`;
  $('promptPreview').hidden=true;
}
function promptRender() {
  const entry=currentPrompt();
  $('promptForm').hidden=!entry;
  if(!entry){promptControls();return;}
  const {data,draft}=entry;
  $('promptProfile').innerHTML=data.profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
  $('promptProfile').value=draft.profile;
  $('promptProfileHint').textContent=data.profiles.find(p=>p.id===draft.profile)?.description||'';
  $('promptSubagent').value=draft.subagent;
  $('promptInstructions').value=draft.instructions;
  $('promptStage').innerHTML=data.stages.map(s=>`<option value="${esc(s.id)}">${esc(s.label)}${draft.stages[s.id]?' · настроен':''}</option>`).join('');
  promptStageRender();
  $('promptApplied').textContent=promptApplied(entry);
  $('promptSaveStatus').textContent=promptDirty(entry)?(entry.reset?'Настройки из конфига готовы к сохранению.':'Есть несохранённые изменения.'):(data.overridden?'Индивидуальные настройки демона.':'Используются настройки конфига.');
  promptControls();promptOptions();
}
function promptChanged() {
  const entry=currentPrompt();if(!entry)return;
  entry.reset=false;
  entry.draft.profile=$('promptProfile').value;
  entry.draft.subagent=$('promptSubagent').value;
  entry.draft.instructions=$('promptInstructions').value;
  entry.draft.stages[entry.stage]=$('promptStageInstructions').value;
  $('promptProfileHint').textContent=entry.data.profiles.find(p=>p.id===entry.draft.profile)?.description||'';
  $('promptStageCount').textContent=`${$('promptStageInstructions').value.length.toLocaleString('ru-RU')} / ${entry.data.max_text||6000} символов`;
  $('promptPreview').hidden=true;
  $('promptSaveStatus').textContent=promptDirty(entry)?'Есть несохранённые изменения.':'Изменений нет.';
  promptControls();promptOptions();
}
async function promptJson(url, options) {
  const response=await fetch(url,options);let data;
  try{data=await response.json();}catch{throw Error('Сервер вернул неожиданный ответ.');}
  if(!response.ok||data.error||data.ok===false)throw Error(data.error||data.reason||'HTTP '+response.status);
  return data;
}
async function promptLoad(id, force=false) {
  promptEditor.id=id; const serial=++promptEditor.serial;
  if(promptEditor.entries.has(id)&&!force){promptEditor.loading=false;$('promptLoadStatus').textContent='';promptRender();return;}
  const previous=promptEditor.entries.get(id), keepDraft=previous?.conflict&&promptDirty(previous);
  promptEditor.loading=true; $('promptLoadStatus').textContent='Загрузка инструкций…';$('promptForm').hidden=true;promptControls();
  try {
    const data=await promptJson('/api/prompts?id='+encodeURIComponent(id));
    if(serial!==promptEditor.serial)return;
    if(!data.available)throw Error(data.error||'Настройки этого демона недоступны.');
    promptEditor.entries.set(id,{data,draft:clonePrompt(keepDraft?(previous.reset?data.defaults:previous.draft):data.values),stage:previous?.stage||'generation',reset:!!(keepDraft&&previous.reset)});
    $('promptLoadStatus').textContent=''; promptRender();
    if(keepDraft)$('promptSaveStatus').textContent='Актуальная версия загружена. Черновик сохранён; проверьте его перед заменой настроек сервера.';
  } catch(error) {if(serial===promptEditor.serial){if(previous)promptRender();$('promptLoadStatus').textContent='Не удалось загрузить инструкции: '+error.message;}}
  finally {if(serial===promptEditor.serial){promptEditor.loading=false;promptControls();}}
}
async function showPrompts(view) {
  promptEditor.visible=view==='prompts';$('prompts').hidden=!promptEditor.visible;
  if(!promptEditor.visible)return;
  if(promptEditor.catalog.length){promptOptions();promptRender();return;}
  promptEditor.loading=true;promptControls();$('promptLoadStatus').textContent='Загрузка демонов…';
  try {
    const data=await promptJson('/api/prompts');
    promptEditor.catalog=data.daemons||[];
    $('promptEmpty').hidden=!!promptEditor.catalog.length;
    if(!promptEditor.catalog.length){$('promptLoadStatus').textContent='';$('promptDaemon').innerHTML='<option value="">Нет доступных демонов</option>';return;}
    promptEditor.id=promptEditor.catalog[0].id;promptOptions();
    await promptLoad(promptEditor.id);
  } catch(error) {$('promptLoadStatus').textContent='Не удалось загрузить демонов: '+error.message;}
  finally {promptEditor.loading=false;promptControls();}
}
$('promptDaemon').addEventListener('change',()=>promptLoad($('promptDaemon').value));
$('promptReload').addEventListener('click',()=>promptEditor.id?promptLoad(promptEditor.id,true):showPrompts('prompts'));
['promptProfile','promptSubagent','promptInstructions','promptStageInstructions'].forEach(id=>$(id).addEventListener('input',promptChanged));
$('promptStage').addEventListener('change',()=>{const entry=currentPrompt();if(entry){entry.stage=$('promptStage').value;promptStageRender();}});
$('promptDiscard').addEventListener('click',()=>{const entry=currentPrompt();if(entry){entry.draft=clonePrompt(entry.data.values);entry.reset=false;promptRender();}});
$('promptDefaults').addEventListener('click',()=>{const entry=currentPrompt();if(entry){entry.draft=clonePrompt(entry.data.defaults);entry.reset=true;promptRender();}});
async function promptPost(action) {
  const entry=currentPrompt(),id=promptEditor.id;if(!entry||promptEditor.busy)return;
  promptEditor.busy=true;promptControls();$('promptSaveStatus').textContent=action==='preview'?'Подготавливаем предпросмотр…':'Сохраняем инструкции…';
  try {
    const data=await promptJson('/api/prompts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,action,revision:entry.data.revision,values:entry.draft,stage:entry.stage})});
    if(action==='preview') {
      const command=data.preview.subagent?`Субагент: /${data.preview.subagent}\n\n`:'';
      $('promptPreviewText').textContent=command+(data.preview.text||'Дополнительных инструкций нет. Используется стандартный запрос Артели для этого этапа.');
      $('promptPreview').hidden=false;
      $('promptSaveStatus').textContent=promptDirty(entry)?'Предпросмотр готов. Правки ещё не сохранены.':'Предпросмотр готов.';
    } else {
      entry.data=data;entry.draft=clonePrompt(data.values);entry.reset=false;promptRender();
      $('promptSaveStatus').textContent='Сохранено для выбранного демона.';
    }
  } catch(error) {
    if(action!=='preview'&&error.message.includes('другой вкладке'))entry.conflict=true;
    $('promptSaveStatus').textContent=(action==='preview'?'Предпросмотр недоступен: ':'Настройки не сохранены: ')+error.message+(entry.conflict?' Нажмите «Сверить с сервером»: черновик останется в редакторе.':'');
  }
  finally {promptEditor.busy=false;promptControls();}
}
$('promptPreviewButton').addEventListener('click',()=>promptPost('preview'));
$('promptForm').addEventListener('submit',event=>{event.preventDefault();if(currentPrompt()?.data.control)promptPost(currentPrompt().reset?'reset':'save');});
window.addEventListener('beforeunload',event=>{if([...promptEditor.entries.values()].some(entry=>promptDirty(entry)&&entry.data.control)){event.preventDefault();event.returnValue='';}});
