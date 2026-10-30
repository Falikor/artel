'use strict';
/* Drafts belong to individual daemons; navigation and refresh never overwrite edits. */
const promptEditor = {visible:false, id:'', entries:new Map(), catalog:[], serial:0, loading:false, busy:false};
const clonePrompt = value => JSON.parse(JSON.stringify(value));
const PROMPT_PROFILE_UI={
  developer:{label:'Developer',description:'Standard Artel behavior.'},
  testing:{label:'Tester',description:'Test scenarios, regressions, and reproducible defects.'},
  custom:{label:'Custom role',description:'Behavior follows your general and stage-specific instructions.'}
};
const PROMPT_STAGE_UI={
  generation:{label:'Task execution',description:'Implement a task or requested requirements rework.'},
  review:{label:'Code review',description:'Independently review changes without editing the working repository.'},
  rework:{label:'Review rework',description:'Address findings from the independent reviewer.'},
  explore:{label:'Backlog exploration',description:'Explore tasks while idle and propose improvements in Jira.'},
  pr_review:{label:'PR feedback',description:'Analyze Bitbucket comments, make fixes, and reply.'},
  retro:{label:'Retrospective',description:'Analyze delivered tasks and extract lessons.'},
  memory:{label:'Memory verification',description:'Verify lesson candidates against code and tests.'}
};
function promptUi(item,field,kind='stage') {
  const original=item?.[field]||'', translated=(kind==='profile'?PROMPT_PROFILE_UI:PROMPT_STAGE_UI)[item?.id]?.[field];
  return translated?tr(original,translated):original;
}
function currentPrompt() { return promptEditor.entries.get(promptEditor.id); }
function comparablePrompt(values) { return JSON.stringify([values.profile,values.subagent,values.instructions,Object.entries(values.stages||{}).filter(([,text])=>text).sort(([a],[b])=>a.localeCompare(b))]); }
function promptDirty(entry) { return !!entry && (entry.reset || comparablePrompt(entry.draft)!==comparablePrompt(entry.data.values)); }
function promptName(row) {
  const resident=(lastSnapshot.daemons||[]).find(d=>d.id===row.id);
  return resident ? daemonOptionName(resident) : [row.name||row.id,row.project].filter(Boolean).join(' · ');
}
function promptOptions() {
  const select=$('promptDaemon');
  select.innerHTML=promptEditor.catalog.map(row=>`<option value="${esc(row.id)}">${esc(promptName(row))}${promptDirty(promptEditor.entries.get(row.id))?tr(" · черновик"," · draft"):''}</option>`).join('');
  select.value=promptEditor.id;
}
function promptControls() {
  const entry=currentPrompt(), dirty=promptDirty(entry), busy=promptEditor.busy;
  $('promptDaemon').disabled=busy||promptEditor.loading;
  $('promptReload').disabled=busy||promptEditor.loading||(dirty&&!entry?.conflict);
  $('promptReload').textContent=entry?.conflict?tr("Сверить с сервером","Check server version"):tr("Обновить","Refresh");
  ['promptProfile','promptSubagent','promptInstructions','promptStage','promptStageInstructions','promptDefaults','promptPreviewButton'].forEach(id=>$(id).disabled=busy||!entry);
  $('promptDiscard').disabled=busy||!dirty;
  $('promptSave').disabled=busy||!dirty||!entry?.data.control;
}
function promptApplied(entry) {
  const data=entry.data;
  if(!data.control) return tr("Режим просмотра: можно проверить инструкции, сохранение отключено.","Read-only mode: you can preview instructions, but cannot save them.");
  if(!data.alive) return tr("Настройки применятся при следующем запуске демона.","Settings will apply the next time the daemon starts.");
  if(!data.supported) return tr("Чтобы применять настройки, перезапустите демона с обновлённым кодом.","Restart the daemon with the updated code to apply settings.");
  if(data.applied?.revision!==data.revision) return tr("Демон применит сохранённые настройки после текущей работы.","The daemon will apply saved settings after the current work finishes.");
  return tr("Сохранённые настройки применены демоном.","Saved settings applied by the daemon.");
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
  $('promptStageHint').textContent=promptUi(stage,'description');
  $('promptStageInstructions').value=entry.draft.stages[entry.stage]||'';
  $('promptStageCount').textContent=`${$('promptStageInstructions').value.length.toLocaleString(uiLocale())} / ${entry.data.max_text||6000} ${tr('символов · пустое поле сохраняет стандартное поведение этапа','characters · leave blank to keep the default stage behavior')}`;
  $('promptPreview').hidden=true;
}
function promptRender() {
  const entry=currentPrompt();
  $('promptForm').hidden=!entry;
  if(!entry){promptControls();return;}
  const {data,draft}=entry;
  $('promptProfile').innerHTML=data.profiles.map(p=>`<option value="${esc(p.id)}">${esc(promptUi(p,'label','profile'))}</option>`).join('');
  $('promptProfile').value=draft.profile;
  $('promptProfileHint').textContent=promptUi(data.profiles.find(p=>p.id===draft.profile),'description','profile');
  $('promptSubagent').value=draft.subagent;
  $('promptInstructions').value=draft.instructions;
  $('promptStage').innerHTML=data.stages.map(s=>`<option value="${esc(s.id)}">${esc(promptUi(s,'label'))}${draft.stages[s.id]?tr(" · настроен"," · customized"):''}</option>`).join('');
  promptStageRender();
  $('promptApplied').textContent=promptApplied(entry);
  $('promptSaveStatus').textContent=promptDirty(entry)?(entry.reset?tr("Настройки из конфига готовы к сохранению.","Configuration defaults are ready to save."):tr("Есть несохранённые изменения.","You have unsaved changes.")):(data.overridden?tr("Индивидуальные настройки демона.","Custom settings for this daemon."):tr("Используются настройки конфига.","Using configuration defaults."));
  promptControls();promptOptions();
  if(!promptDirty(entry))markFormClean($('promptForm'));
}
function promptChanged() {
  const entry=currentPrompt();if(!entry)return;
  entry.reset=false;
  entry.draft.profile=$('promptProfile').value;
  entry.draft.subagent=$('promptSubagent').value;
  entry.draft.instructions=$('promptInstructions').value;
  entry.draft.stages[entry.stage]=$('promptStageInstructions').value;
  $('promptProfileHint').textContent=promptUi(entry.data.profiles.find(p=>p.id===entry.draft.profile),'description','profile');
  $('promptStageCount').textContent=`${$('promptStageInstructions').value.length.toLocaleString(uiLocale())} / ${entry.data.max_text||6000} ${tr('символов','characters')}`;
  $('promptPreview').hidden=true;
  $('promptSaveStatus').textContent=promptDirty(entry)?tr("Есть несохранённые изменения.","You have unsaved changes."):tr("Изменений нет.","No changes.");
  promptControls();promptOptions();
}
async function promptJson(url, options) {
  const response=await fetch(url,options);let data;
  try{data=await response.json();}catch{throw Error(tr("Сервер вернул неожиданный ответ.","The server returned an unexpected response."));}
  if(!response.ok||data.error||data.ok===false)throw Error(data.error||data.reason||'HTTP '+response.status);
  return data;
}
async function promptLoad(id, force=false) {
  promptEditor.id=id; const serial=++promptEditor.serial;
  if(promptEditor.entries.has(id)&&!force){promptEditor.loading=false;$('promptLoadStatus').textContent='';promptRender();return;}
  const previous=promptEditor.entries.get(id), keepDraft=previous?.conflict&&promptDirty(previous);
  promptEditor.loading=true; $('promptLoadStatus').textContent=tr("Загрузка инструкций…","Loading instructions…");$('promptForm').hidden=true;promptControls();
  try {
    const data=await promptJson('/api/prompts?id='+encodeURIComponent(id));
    if(serial!==promptEditor.serial)return;
    if(!data.available)throw Error(data.error||tr("Настройки этого демона недоступны.","Settings are not available for this daemon."));
    promptEditor.entries.set(id,{data,draft:clonePrompt(keepDraft?(previous.reset?data.defaults:previous.draft):data.values),stage:previous?.stage||'generation',reset:!!(keepDraft&&previous.reset)});
    $('promptLoadStatus').textContent=''; promptRender();
    if(keepDraft)$('promptSaveStatus').textContent=tr("Актуальная версия загружена. Черновик сохранён; проверьте его перед заменой настроек сервера.","Latest version loaded. Your draft is preserved; review it before replacing the server settings.");
  } catch(error) {if(serial===promptEditor.serial){if(previous)promptRender();$('promptLoadStatus').textContent=tr("Не удалось загрузить инструкции: ","Could not load instructions: ")+translateServerMessage(error.message);}}
  finally {if(serial===promptEditor.serial){promptEditor.loading=false;promptControls();}}
}
async function showPrompts(view) {
  promptEditor.visible=view==='prompts';$('prompts').hidden=!promptEditor.visible;
  if(!promptEditor.visible)return;
  if(promptEditor.catalog.length){promptOptions();promptRender();return;}
  promptEditor.loading=true;promptControls();$('promptLoadStatus').textContent=tr("Загрузка демонов…","Loading daemons…");
  try {
    const data=await promptJson('/api/prompts');
    promptEditor.catalog=data.daemons||[];
    $('promptEmpty').hidden=!!promptEditor.catalog.length;
    if(!promptEditor.catalog.length){$('promptLoadStatus').textContent='';$('promptDaemon').innerHTML=`<option value="">${tr('Нет доступных демонов','No daemons available')}</option>`;return;}
    promptEditor.id=promptEditor.catalog[0].id;promptOptions();
    await promptLoad(promptEditor.id);
  } catch(error) {$('promptLoadStatus').textContent=tr("Не удалось загрузить демонов: ","Could not load daemons: ")+translateServerMessage(error.message);}
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
  promptEditor.busy=true;promptControls();$('promptSaveStatus').textContent=action==='preview'?tr("Подготавливаем предпросмотр…","Preparing preview…"):tr("Сохраняем инструкции…","Saving instructions…");
  try {
    const data=await promptJson('/api/prompts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,action,revision:entry.data.revision,values:entry.draft,stage:entry.stage})});
    if(action==='preview') {
      const command=data.preview.subagent?`${tr('Субагент','Subagent')}: /${data.preview.subagent}\n\n`:'';
      $('promptPreviewText').textContent=command+(data.preview.text||tr("Дополнительных инструкций нет. Используется стандартный запрос Артели для этого этапа.","No additional instructions. Artel uses the default prompt for this stage."));
      $('promptPreview').hidden=false;
      $('promptSaveStatus').textContent=promptDirty(entry)?tr("Предпросмотр готов. Правки ещё не сохранены.","Preview ready. Your changes have not been saved."):tr("Предпросмотр готов.","Preview ready.");
    } else {
      entry.data=data;entry.draft=clonePrompt(data.values);entry.reset=false;promptRender();markFormClean($('promptForm'));
      $('promptSaveStatus').textContent=tr("Сохранено для выбранного демона.","Saved for the selected daemon.");
    }
  } catch(error) {
    if(action!=='preview'&&error.message.includes('другой вкладке'))entry.conflict=true;
    $('promptSaveStatus').textContent=(action==='preview'?tr("Предпросмотр недоступен: ","Preview unavailable: "):tr("Настройки не сохранены: ","Settings were not saved: "))+translateServerMessage(error.message)+(entry.conflict?tr(" Нажмите «Сверить с сервером»: черновик останется в редакторе."," Select “Check server version”; your draft will remain in the editor."):'');
  }
  finally {promptEditor.busy=false;promptControls();}
}
$('promptPreviewButton').addEventListener('click',()=>promptPost('preview'));
$('promptForm').addEventListener('submit',event=>{event.preventDefault();if(currentPrompt()?.data.control)promptPost(currentPrompt().reset?'reset':'save');});
window.addEventListener('beforeunload',event=>{if(window.artelLanguageReloadApproved===true)return;if([...promptEditor.entries.values()].some(entry=>promptDirty(entry)&&entry.data.control)){event.preventDefault();event.returnValue='';}});
