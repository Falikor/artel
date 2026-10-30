'use strict';
const cliMonitor = {source:null,id:null,technical:false,data:null,nodes:new Map()};
function stopMonitor() {
  if(cliMonitor.source)cliMonitor.source.close();
  cliMonitor.source=null;cliMonitor.id=null;cliMonitor.data=null;cliMonitor.renderKey=null;cliMonitor.nodes.clear();
}
function startMonitor(id,technical) {
  cliMonitor.technical=technical;
  if(cliMonitor.id===id&&cliMonitor.source){renderMonitor();return;}
  stopMonitor();cliMonitor.id=id;cliMonitor.technical=technical;
  $('monitorEvents').textContent='';$('monitorStatus').textContent='Подключение к журналу GigaCode…';
  const source=new EventSource('/api/cli-events?id='+encodeURIComponent(id));cliMonitor.source=source;
  source.onmessage=event=>{
    if(cliMonitor.source!==source)return;
    try{cliMonitor.data=JSON.parse(event.data);cliMonitor.disconnected=false;renderMonitor();}
    catch{$('monitorStatus').textContent='Не удалось прочитать события. Ожидаем следующее обновление.';}
  };
  source.onerror=()=>{if(cliMonitor.source===source){cliMonitor.disconnected=true;$('monitorStatus').textContent='Связь потеряна. Переподключаемся автоматически; полученные события сохранены.';}};
}
function renderMonitor() {
  const data=cliMonitor.data;if(!data)return;
  const cli=data.cli, daemon=lastSnapshot.daemons.find(d=>d.id===cliMonitor.id);
  const states={running:'GigaCode выполняет задачу',success:'GigaCode завершил выполнение',error:'Ошибка выполнения',timeout:'Превышено время ожидания',interrupted:'Выполнение прервано'};
  if(!cliMonitor.disconnected)$('monitorStatus').textContent=cli ? (cli.active&&daemon&&!daemon.alive?'Нет сигнала от демона. Итог выполнения неизвестен.':states[cli.status]||'Ожидаем события')+(cli.issue?' · '+cli.issue:'')+(data.truncated?' · Последние 256 событий':'') : 'GigaCode ещё не запускался. Когда демон возьмёт задачу, действия появятся здесь в реальном времени.';
  $('monitorStatus').dataset.state=cli?.status||'empty';
  const renderKey=[data.executionId,data.lastSeq,cliMonitor.technical].join(':');if(cliMonitor.renderKey===renderKey)return;
  const oldView=cliMonitor.renderKey?.split(':').pop();
  if(oldView!==String(cliMonitor.technical)){cliMonitor.nodes.clear();$('monitorEvents').textContent='';}
  cliMonitor.renderKey=renderKey;
  const list=$('monitorEvents'),events=data.events||[],keys=new Set();
  for(const event of events){
    const key=event.executionId+':'+event.seq;keys.add(key);
    if(cliMonitor.nodes.has(key))continue;
    const node=document.createElement('li');
    node.dataset.event=key;
    const error=['tool_error','parse_error','error','timeout','interrupted'].includes(event.kind);
    node.className=error?'monitor-error':'';
    const timestamp=new Date(Number(event.timestamp)*1000),validTime=Number.isFinite(timestamp.getTime()),time=validTime?timestamp.toLocaleTimeString('ru-RU'):'—';
    const heading=`<time${validTime?' datetime="'+timestamp.toISOString()+'"':''}>${esc(time)}</time><span>${esc(event.summary)}</span>`;
    if(cliMonitor.technical&&event.detail){
      const expanded=['error','tool_error','parse_error','timeout','interrupted'].includes(event.kind);
      node.innerHTML=`<details${expanded?' open':''}><summary>${heading}<span class="monitor-chevron" aria-hidden="true">›</span></summary><div class="monitor-detail"><small>${esc(event.kind)} · #${Number(event.seq)}${event.toolUseId?' · '+esc(event.toolUseId):''}</small><pre tabindex="0">${esc(event.detail)}</pre></div></details>`;
    }else node.innerHTML=`<div class="monitor-entry">${heading}</div>`;
    cliMonitor.nodes.set(key,node);list.appendChild(node);
  }
  for(const [key,node]of cliMonitor.nodes){if(!keys.has(key)){node.remove();cliMonitor.nodes.delete(key);}}
  drawerScrollEnd();
}
function monitorText() {
  return (cliMonitor.data?.events||[]).map(event=>new Date(event.timestamp*1000).toLocaleTimeString('ru-RU')+' '+event.summary+(cliMonitor.technical&&event.detail?'\n'+event.detail:'')).join('\n\n');
}
