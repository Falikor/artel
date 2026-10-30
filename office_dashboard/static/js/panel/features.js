'use strict';
let featureLoading=false,featureSaving=false,featureData=null,featureLoadedAt=0,featureReadVersion=0,featureDaemon=null;
async function loadFeaturePanel(force=false) {
  if(!drawer.id||featureLoading||featureSaving||(!force&&featureDaemon===drawer.id&&Date.now()-featureLoadedAt<3000))return;
  const id=drawer.id,version=++featureReadVersion;featureLoading=true;
  try {
    const response=await fetch('/api/features?id='+encodeURIComponent(id));
    if(!response.ok)throw Error('HTTP '+response.status);
    const data=await response.json();if(id!==drawer.id||version!==featureReadVersion)return;
    featureData=data;featureLoadedAt=Date.now();featureDaemon=id;
    if(!data.available){$('featureRows').textContent='';$('featureRows')._markup=null;$('featureStatus').textContent=data.error||'Для управления функциями запустите демона с конфигом.';return;}
    const applied=data.applied,pending=!applied||applied.revision!==data.revision;
    $('featureStatus').textContent=!data.supported?'Для применения нужен демон версии 2.18.0 или новее.':!data.alive?'Настройки применятся при запуске демона.':pending?'Демон применит настройки после текущей работы.':'Настройки применены демоном.';
    if(document.activeElement?.closest('#featureRows'))return;
    drawerMarkup($('featureRows'),data.catalog.map(feature=>{
      const value=Object.hasOwn(data.overrides,feature.key)?String(data.overrides[feature.key]):'config';
      const effective=(applied?.effective||[]).map(row=>{
        const dependencyOff=(feature.dependency&&!row.values[feature.dependency])||(feature.key==='explore.learn'&&(!row.values['jira.enabled']||!row.values['memory.enabled']));
        return `${row.service?row.service+': ':''}${dependencyOff?'ожидает включения зависимости':row.values[feature.key]?'включено':'выключено'}`;
      }).join(' · ')||'Ещё не применено';
      return `<label class="feature-row"><span>${esc(feature.label)}<small>${esc(feature.supported===false?'Нужен демон 2.19.0 или новее':effective)}</small></span><select aria-label="${esc(feature.label)}" data-feature="${esc(feature.key)}" ${data.control&&feature.supported!==false?'':'disabled'}>${[['config','По конфигу'],['true','Включить'],['false','Выключить']].map(([option,label])=>`<option value="${option}"${value===option?' selected':''}>${label}</option>`).join('')}</select></label>`;
    }).join(''));
  }catch(error){if(id===drawer.id)$('featureStatus').textContent='Не удалось загрузить настройки. '+error.message;}
  finally{featureLoading=false;}
}
$('featureRows').addEventListener('change',async event=>{
  const select=event.target.closest('[data-feature]');if(!select||featureSaving||!featureData||featureDaemon!==drawer.id)return;
  const id=drawer.id,key=select.dataset.feature,previous=Object.hasOwn(featureData.overrides,key)?String(featureData.overrides[key]):'config';
  featureReadVersion++;featureSaving=true;
  const fields=[...$('featureRows').querySelectorAll('select')],disabled=fields.map(field=>field.disabled);fields.forEach(field=>field.disabled=true);
  $('featureStatus').textContent='Сохраняем настройку…';
  try {
    const response=await fetch('/api/features',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,key,value:select.value==='config'?null:select.value==='true',revision:featureData.revision})});
    const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||result.reason||'HTTP '+response.status);
    if(id===drawer.id){featureData.revision=result.revision;featureData.overrides=result.overrides;$('featureRows')._markup=null;$('featureStatus').textContent='Сохранено. Применится после текущей работы.';}
  }catch(error){if(id===drawer.id){select.value=previous;$('featureStatus').textContent='Настройка не сохранена: '+error.message;}}
  finally{featureSaving=false;fields.forEach((field,index)=>field.disabled=disabled[index]);featureLoadedAt=0;}
});
