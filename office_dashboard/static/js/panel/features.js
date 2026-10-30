'use strict';
function featureLabel(feature) {
  const labels={
    'jira.enabled':['Jira: получение и обработка задач','Jira: find and process tasks'],
    'bitbucket.enabled':['Bitbucket: замечания к PR','Bitbucket: PR feedback'],
    'memory.enabled':['Память: чтение и обучение','Memory: read and learn'],
    'memory.auto_append':['Сохранять кандидатов на уроки','Collect lesson candidates'],
    'memory.auto_verify':['Проверять уроки автоматически','Verify lessons automatically'],
    'review.enabled':['Независимое ревью кода','Independent code review'],
    'explore.enabled':['Исследование бэклога','Backlog exploration'],
    'explore.learn':['Учиться при исследовании бэклога','Learn from backlog exploration'],
    'retro.enabled':['Ретроспектива сданных задач','Delivered-task retrospectives'],
    'jenkins.enabled':['Деплой Jenkins по лейблу задачи','Jenkins deployment by issue label'],
    'requirements.enabled':['Ручные переделки постановки','Requested requirements rework'],
    'dependencies.enabled':['Порядок связанных задач: бэкенд → фронтенд','Linked task order: backend → frontend']
  };
  return labels[feature.key]?tr(...labels[feature.key]):translateServerMessage(feature.label||feature.key);
}
let featureLoading=false,featureSaving=false,featureData=null,featureLoadedAt=0,featureReadVersion=0,featureDaemon=null;
async function loadFeaturePanel(force=false) {
  if(!drawer.id||featureLoading||featureSaving||(!force&&featureDaemon===drawer.id&&Date.now()-featureLoadedAt<3000))return;
  const id=drawer.id,version=++featureReadVersion;featureLoading=true;
  try {
    const response=await fetch('/api/features?id='+encodeURIComponent(id));
    if(!response.ok)throw Error('HTTP '+response.status);
    const data=await response.json();if(id!==drawer.id||version!==featureReadVersion)return;
    featureData=data;featureLoadedAt=Date.now();featureDaemon=id;
    if(!data.available){$('featureRows').textContent='';$('featureRows')._markup=null;$('featureStatus').textContent=data.error?translateServerMessage(data.error):tr("Для управления функциями запустите демона с конфигом.","Start the daemon with a configuration to manage its features.");return;}
    const applied=data.applied,pending=!applied||applied.revision!==data.revision;
    $('featureStatus').textContent=!data.supported?tr("Для применения нужен демон версии 2.18.0 или новее.","Daemon version 2.18.0 or later is required."):!data.alive?tr("Настройки применятся при запуске демона.","Settings will apply when the daemon starts."):pending?tr("Демон применит настройки после текущей работы.","Settings will apply after the current work finishes."):tr("Настройки применены демоном.","Settings applied by the daemon.");
    if(document.activeElement?.closest('#featureRows'))return;
    drawerMarkup($('featureRows'),data.catalog.map(feature=>{
      const value=Object.hasOwn(data.overrides,feature.key)?String(data.overrides[feature.key]):'config';
      const effective=(applied?.effective||[]).map(row=>{
        const dependencyOff=(feature.dependency&&!row.values[feature.dependency])||(feature.key==='explore.learn'&&(!row.values['jira.enabled']||!row.values['memory.enabled']));
        return `${row.service?row.service+': ':''}${dependencyOff?tr("ожидает включения зависимости","waiting for a required feature"):row.values[feature.key]?tr("включено","enabled"):tr("выключено","disabled")}`;
      }).join(' · ')||tr("Ещё не применено","Not applied yet");
      return `<label class="feature-row"><span>${esc(featureLabel(feature))}<small>${esc(feature.supported===false?tr("Нужен демон 2.19.0 или новее","Daemon 2.19.0 or later required"):effective)}</small></span><select aria-label="${esc(featureLabel(feature))}" data-feature="${esc(feature.key)}" ${data.control&&feature.supported!==false?'':'disabled'}>${[['config',tr("По конфигу","Use configuration")],['true',tr("Включить","Enable")],['false',tr("Выключить","Disable")]].map(([option,label])=>`<option value="${option}"${value===option?' selected':''}>${label}</option>`).join('')}</select></label>`;
    }).join(''));
  }catch(error){if(id===drawer.id)$('featureStatus').textContent=tr("Не удалось загрузить настройки. ","Could not load settings. ")+translateServerMessage(error.message);}
  finally{featureLoading=false;}
}
$('featureRows').addEventListener('change',async event=>{
  const select=event.target.closest('[data-feature]');if(!select||featureSaving||!featureData||featureDaemon!==drawer.id)return;
  const id=drawer.id,key=select.dataset.feature,previous=Object.hasOwn(featureData.overrides,key)?String(featureData.overrides[key]):'config';
  featureReadVersion++;featureSaving=true;
  const fields=[...$('featureRows').querySelectorAll('select')],disabled=fields.map(field=>field.disabled);fields.forEach(field=>field.disabled=true);
  $('featureStatus').textContent=tr("Сохраняем настройку…","Saving setting…");
  try {
    const response=await fetch('/api/features',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,key,value:select.value==='config'?null:select.value==='true',revision:featureData.revision})});
    const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||result.reason||'HTTP '+response.status);
    if(id===drawer.id){featureData.revision=result.revision;featureData.overrides=result.overrides;markFormClean($('featureRows'));$('featureRows')._markup=null;$('featureStatus').textContent=tr("Сохранено. Применится после текущей работы.","Saved. Applies after the current work finishes.");}
  }catch(error){if(id===drawer.id){select.value=previous;markFormClean(select);$('featureStatus').textContent=tr("Настройка не сохранена: ","Setting was not saved: ")+translateServerMessage(error.message);}}
  finally{featureSaving=false;fields.forEach((field,index)=>field.disabled=disabled[index]);featureLoadedAt=0;}
});
