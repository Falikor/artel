'use strict';
const MONITOR_SUMMARIES={
  'Изучает структуру проекта':'Exploring project structure',
  'Анализирует исходный код':'Analyzing source code',
  'Вносит изменения в файлы':'Editing files',
  'Выполняет команду':'Running a command',
  'Вызывает инструмент':'Calling a tool',
  'Агент начал выполнение':'Agent started execution',
  'GigaCode завершил выполнение; Артель проверяет результат':'GigaCode finished; Artel is verifying the result',
  'Выполнение GigaCode завершилось с ошибкой':'GigaCode execution failed',
  'Выполнение прервано':'Execution interrupted',
  'Истекло время выполнения':'Execution timed out',
  'Слишком большое событие CLI; требуется проверка':'CLI event is too large; review required',
  'Не удалось прочитать событие CLI':'Could not read a CLI event',
  'Некорректный ID сессии CLI':'Invalid CLI session ID',
  'Сессия GigaCode подключена':'GigaCode session connected',
  'Неизвестный формат содержимого CLI':'Unknown CLI content format',
  'Вызов инструмента без имени или ID':'Tool call has no name or ID',
  'Инструмент сообщил об ошибке':'Tool reported an error',
  'Инструмент завершил работу':'Tool finished',
  'Агент подготовил сообщение':'Agent prepared a message',
  'Получено неподдерживаемое событие CLI':'Unsupported CLI event received',
  'Вложенный агент завершил ход':'Subagent finished its turn',
  'Получен итоговый ответ GigaCode':'GigaCode final response received',
  'GigaCode сообщил об ошибке':'GigaCode reported an error',
  'Ошибка формата события CLI':'Invalid CLI event format',
  'Ошибка чтения потока CLI':'Could not read the CLI stream',
  'Получено диагностическое сообщение CLI':'CLI diagnostic message received'
};
function monitorSummary(event) {
  const summary=event.summary||'';
  return Object.hasOwn(MONITOR_SUMMARIES,summary)?tr(summary,MONITOR_SUMMARIES[summary]):summary;
}
const cliMonitor = {source:null,id:null,technical:false,data:null,nodes:new Map()};
function stopMonitor() {
  if(cliMonitor.source)cliMonitor.source.close();
  cliMonitor.source=null;cliMonitor.id=null;cliMonitor.data=null;cliMonitor.renderKey=null;cliMonitor.nodes.clear();
}
function startMonitor(id,technical) {
  cliMonitor.technical=technical;
  if(cliMonitor.id===id&&cliMonitor.source){renderMonitor();return;}
  stopMonitor();cliMonitor.id=id;cliMonitor.technical=technical;
  $('monitorEvents').textContent='';$('monitorStatus').textContent=tr("Подключение к журналу GigaCode…","Connecting to the GigaCode log…");
  const source=new EventSource('/api/cli-events?id='+encodeURIComponent(id));cliMonitor.source=source;
  source.onmessage=event=>{
    if(cliMonitor.source!==source)return;
    try{cliMonitor.data=JSON.parse(event.data);cliMonitor.disconnected=false;renderMonitor();}
    catch{$('monitorStatus').textContent=tr("Не удалось прочитать события. Ожидаем следующее обновление.","Could not read events. Waiting for the next update.");}
  };
  source.onerror=()=>{if(cliMonitor.source===source){cliMonitor.disconnected=true;$('monitorStatus').textContent=tr("Связь потеряна. Переподключаемся автоматически; полученные события сохранены.","Connection lost. Reconnecting automatically; received events are preserved.");}};
}
function renderMonitor() {
  const data=cliMonitor.data;if(!data)return;
  const cli=data.cli, daemon=lastSnapshot.daemons.find(d=>d.id===cliMonitor.id);
  const states={running:tr("GigaCode выполняет задачу","GigaCode is working on the task"),success:tr("GigaCode завершил выполнение","GigaCode completed the task"),error:tr("Ошибка выполнения","Execution error"),timeout:tr("Превышено время ожидания","Execution timed out"),interrupted:tr("Выполнение прервано","Execution interrupted")};
  if(!cliMonitor.disconnected)$('monitorStatus').textContent=cli ? (cli.active&&daemon&&!daemon.alive?tr("Нет сигнала от демона. Итог выполнения неизвестен.","No signal from the daemon. Execution outcome is unknown."):states[cli.status]||tr("Ожидаем события","Waiting for events"))+(cli.issue?' · '+cli.issue:'')+(data.truncated?tr(" · Последние 256 событий"," · Last 256 events"):'') : tr("GigaCode ещё не запускался. Когда демон возьмёт задачу, действия появятся здесь в реальном времени.","GigaCode has not run yet. Activity will appear here live when the daemon starts a task.");
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
    const timestamp=new Date(Number(event.timestamp)*1000),validTime=Number.isFinite(timestamp.getTime()),time=validTime?timestamp.toLocaleTimeString(uiLocale()):'—';
    const heading=`<time${validTime?' datetime="'+timestamp.toISOString()+'"':''}>${esc(time)}</time><span>${esc(monitorSummary(event))}</span>`;
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
  return (cliMonitor.data?.events||[]).map(event=>new Date(event.timestamp*1000).toLocaleTimeString(uiLocale())+' '+monitorSummary(event)+(cliMonitor.technical&&event.detail?'\n'+event.detail:'')).join('\n\n');
}
