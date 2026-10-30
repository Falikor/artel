'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const scripts = path.join(__dirname, '../office_dashboard/static/js');
function harness(language = 'ru') {
  const elements = new Map(), listeners = new Map(), focus = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value: id === 'workspaceDays' ? '30' : '', innerHTML: '',
      querySelectorAll: () => [], querySelector: () => null, setAttribute() {},
      focus: options => focus.push({id, options}),
      addEventListener(type, listener) { const key = id + ':' + type; if (!listeners.has(key)) listeners.set(key, []); listeners.get(key).push(listener); }});
    return elements.get(id);
  };
  const context = vm.createContext({tr:(ru,en)=>language === 'en' ? en : ru, uiLocale:()=>language === 'en' ? 'en-US' : 'ru-RU', translateServerMessage:message=>message, markFormClean(){}, Date, URLSearchParams, setTimeout, clearTimeout, setInterval, clearInterval,
    $: element, esc: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;'),
    document: {querySelector: () => null, getElementById: element}, displayName: d => d.id,
    lastSnapshot: {daemons: [], offices: []}, fmtTokens: String, window: {},
  });
  const run = code => vm.runInContext(code, context);
  for (const file of ['core/pagination.js', 'stats/workspace.js', 'stats/requirements.js', 'stats/proposals.js', 'stats/quality.js', 'stats/stats.js']) {
    let source = fs.readFileSync(path.join(scripts, file), 'utf8');
    if (file === 'stats/stats.js') source = source.replace(/\nsetupStats\(\);\s*$/, '\n');
    vm.runInContext(source, context, {filename: file});
  }
  const more = (key, render = () => {}, allowed = () => true) => context.sectionPaginationClick(
    {target: {closest: () => ({dataset: {pageMore: key}})}}, render, allowed);
  return {context, run, element, more, focus, listeners};
}
const rowsIn = html => (html.match(/<tbody>[\s\S]*?<\/tbody>/)?.[0].match(/<tr>/g) || []).length;
const records = (n = 45) => Array.from({length:n}, (_, i) => ({id:'d'+i, issue:'ART-'+i, result:'ok',
  finished_at: Date.now()/1000, gen_seconds:60, total_seconds:90, tokens:{total:100}, attempts:1}));

test('sections reveal 20, 40, then all 45 records and finish without a dead button', () => {
  const h = harness(), rows = records();
  let page = h.context.sectionPage('test:records', rows, '', 'Журнал');
  assert.equal(page.rows.length,20); assert.match(page.footer,/Показано 20 из 45/);
  h.more('test:records'); page = h.context.sectionPage('test:records', rows, '', 'Журнал');
  assert.equal(page.rows.length,40); assert.match(page.footer,/показать ещё 5/);
  h.more('test:records'); page = h.context.sectionPage('test:records', rows, '', 'Журнал');
  assert.equal(page.rows.length,45); assert.doesNotMatch(page.footer,/data-page-more/);
  assert.equal(rows.length,45); assert.equal(h.context.sectionPage('test:empty',[]).footer,'');
  assert.equal(h.focus.at(-1).options.preventScroll,true);
});
test('auto refresh preserves expansion; filters reset it, including a filter with no results', () => {
  const h=harness(), rows=records();
  h.context.sectionPaginationContext('stats','all');
  h.context.sectionPage('stats:journal',rows,'all'); h.more('stats:journal');
  h.context.sectionPaginationContext('stats','all');
  assert.equal(h.context.sectionPage('stats:journal',records(50),'all').rows.length,40);
  h.context.sectionPaginationContext('stats','empty');
  h.context.sectionPaginationContext('stats','all');
  assert.equal(h.context.sectionPage('stats:journal',rows,'all').rows.length,20);
});
test('independent sections and open editors cannot accidentally reveal another page', () => {
  const h=harness(), rows=records();
  h.context.sectionPage('stats:journal',rows); h.context.sectionPage('stats:proposals',rows);
  h.more('stats:journal');
  assert.equal(h.context.sectionPage('stats:proposals',rows).rows.length,20);
  let rendered=false;
  h.more('stats:journal',()=>{rendered=true;},()=>false);
  assert.equal(rendered,false); assert.equal(h.context.sectionPage('stats:journal',rows).rows.length,40);
});
test('journal reveals beyond its former 400 row cap; search restarts at 20', () => {
  const h=harness(); h.context.records=records(421);
  h.run("stats.period='all'; stats.data={daemons:{},records};");
  assert.equal(rowsIn(h.context.renderJournal(h.context.records)),20);
  for(let i=0;i<21;i++) h.more('stats:journal');
  assert.equal(rowsIn(h.context.renderJournal(h.context.records)),421);
  h.run("stats.query='ART';");
  assert.equal(rowsIn(h.context.renderJournal(h.context.records)),20);
});
test('demon sorting resets only its page; task totals include records beyond the page', () => {
  const h=harness(); h.context.records=records();
  h.run("stats.period='all'; stats.data={daemons:{},records};");
  assert.equal(rowsIn(h.context.renderDemonTable(h.context.records,[])),20);
  h.context.renderJournal(h.context.records); h.more('stats:journal'); h.more('stats:demons');
  assert.equal(rowsIn(h.context.renderDemonTable(h.context.records,[])),40);
  h.run("stats.sort='name';");
  assert.equal(rowsIn(h.context.renderDemonTable(h.context.records,[])),20);
  assert.equal(rowsIn(h.context.renderJournal(h.context.records)),40);
  const totals=h.context.renderKpis(h.context.records,[]);
  assert.match(totals,/Закрыто задач<\/div><div class="kpi-value">45<\/div>/);
  assert.match(totals,/4500/);
});
test('unfinished task summary distinguishes BLOCKED from failed attempts across all pages', () => {
  const h=harness(), rows=records();
  rows.slice(0,9).forEach(r=>{r.result='blocked';});rows.slice(9,18).forEach(r=>{r.result='fail';});
  const totals=h.context.renderKpis(rows,[]);
  assert.match(totals,/Не сделано<\/div><div class="kpi-value">18<\/div>/);
  assert.match(totals,/9 — последняя попытка с ошибкой/);assert.match(totals,/9 ждут уточнения в Jira/);
  assert.match(totals,/Закрыто задач<\/div><div class="kpi-value">27<\/div>/);
  const waiting=h.context.renderKpis(rows.filter(r=>r.result==='blocked'),[]);
  assert.doesNotMatch(waiting,/попытка с ошибкой|попытка — ошибка/);assert.match(waiting,/9 ждут уточнения в Jira/);
});
test('proposals and quality tables have separate accessible footers', () => {
  const h=harness(); h.context.records=records(); h.run('stats.data={daemons:{},records};');
  const proposals=h.context.records.map(r=>({...r,result:'posted'}));
  assert.equal(rowsIn(h.context.renderProposals(proposals)),20);
  h.more('stats:proposals'); assert.equal(rowsIn(h.context.renderProposals(proposals)),40);
  const quality=h.context.records.map(r=>({...r,total:1,as_is:1,as_is_share:1}));
  assert.equal(rowsIn(h.context.qualityTable(quality)),20);
  h.more('stats:quality'); assert.equal(rowsIn(h.context.qualityTable(quality)),40);
  assert.match(h.context.qualityTable(quality),/aria-label="Исходы по демонам: показать ещё 5"/);
});
test('analytics paginates service groups while keeping all-task totals', () => {
  const h=harness(); h.run("workspace.view='analytics';");
  const data={totals:{tasks:45,completed:45,attempts:45,failed_attempts:0,first_pass:45,tokens:4500,token_coverage:45},
    groups:records().map(r=>({...r,tasks:1,attempts:1,failed_attempts:0,tokens:100}))};
  h.context.drawAnalytics(data);
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),20);
  assert.match(h.element('workspaceBody').innerHTML,/Задач<\/div><div class="kpi-value">45<\/div>/);
  h.more('workspace-analytics:groups',()=>h.context.drawAnalytics(data));
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),40);
});
test('retrospective and requirement records expand without changing their full summaries', () => {
  const h=harness(); h.run("workspace.view='retro';");
  const retro={summary:{totals:{as_is:45}},rows:records().map(r=>({...r,category:'as_is',delivered_at:r.finished_at}))};
  h.context.drawRetrospective(retro); assert.equal(rowsIn(h.element('workspaceBody').innerHTML),20);
  h.more('workspace-retro:tasks',()=>h.context.drawRetrospective(retro));
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),40);
  h.element('workspaceSearch').value='ART-1'; h.context.drawRetrospective(retro);
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),11);
  h.element('workspaceSearch').value=''; h.context.drawRetrospective(retro);
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),20);
  h.run("workspace.view='requirements';");
  const requests={control:false,rows:records().map((r,i)=>({...r,request:'r'+i,created_at:r.finished_at,status:'done',note:'New requirements'}))};
  h.context.drawRequirements(requests); assert.equal(rowsIn(h.element('workspaceBody').innerHTML),20);
  assert.match(h.element('workspaceBody').innerHTML,/Завершено<\/div><div class="kpi-value">45<\/div>/);
  h.more('workspace-requirements:requests',()=>h.context.drawRequirements(requests));
  assert.equal(rowsIn(h.element('workspaceBody').innerHTML),40);
});
test('memory sources paginate independently and status filters reset them', () => {
  const h=harness(); h.context.memory={available:true,control:false,sources:['alpha','beta'].map(key=>({key,id:key,
    entries:records().map((r,i)=>({id:'e'+i,text:'Lesson '+i,status:'confirmed'}))}))};
  h.run("workspace.view='memory'; workspace.memory=memory; drawMemory();");
  const count=()=> (h.element('workspaceBody').innerHTML.match(/class="memory-entry"/g)||[]).length;
  assert.equal(count(),40);
  h.more('workspace-memory:source:alpha',()=>h.context.drawMemory()); assert.equal(count(),60);
  assert.match(h.element('workspaceBody').innerHTML,/Записей<\/div><div class="kpi-value">90<\/div>/);
  h.element('memoryFilter').value='candidate';h.context.drawMemory();assert.equal(count(),0);
  h.element('memoryFilter').value='';h.context.drawMemory();assert.equal(count(),40);
});

test('English journal pagination keeps totals and independent sections intact', () => {
  const h = harness('en'), rows = records();
  h.context.records = rows; h.run("stats.period='all'; stats.data={daemons:{},records};");
  let journal = h.context.renderJournal(rows);
  assert.match(journal, /Showing 20 of 45/);
  assert.match(journal, /aria-label="Task journal: show more 20"/);
  assert.match(journal, /<th>Outcome<\/th>/);
  assert.equal(rowsIn(journal), 20);
  h.more('stats:journal'); journal = h.context.renderJournal(rows);
  assert.match(journal, /Showing 40 of 45/); assert.equal(rowsIn(journal), 40);
  const proposals = h.context.renderProposals(rows.map(row => ({...row, result:'posted'})));
  assert.match(proposals, /Showing 20 of 45/); assert.equal(rowsIn(proposals), 20);
  h.more('stats:journal'); journal = h.context.renderJournal(rows);
  assert.match(journal, /Showing 45 of 45/); assert.doesNotMatch(journal, /data-page-more/);
  assert.match(h.context.renderKpis(rows, []), /Completed tasks<\/div><div class="kpi-value">45<\/div>/);
  assert.equal(rows.length, 45);
});

test('English statistics and workspace renderers localize static copy and number formatting', () => {
  const h = harness('en'), rows = records();
  h.context.records = rows; h.run("stats.period='all'; stats.data={daemons:{},records};");
  const rendered = [h.context.renderKpis(rows, []), h.context.renderJournal(rows),
    h.context.renderDemonTable(rows, []), h.context.renderPricesForm(),
    h.context.renderProposals(rows.map(row => ({...row, result:'posted'})))];
  h.context.drawRetrospective({summary:{totals:{as_is:45}}, rows:rows.map(row => ({
    ...row, category:'as_is', delivered_at:row.finished_at, human_commits:0, human_lines:0, followups:0}))});
  rendered.push(h.element('workspaceBody').innerHTML);
  h.context.drawRequirements({control:false, rows:rows.map((row, i) => ({
    ...row, request:'r'+i, created_at:row.finished_at, status:'done', note:'New requirements'}))});
  rendered.push(h.element('workspaceBody').innerHTML);
  h.context.memory = {available:true, control:true, sources:[{key:'alpha', id:'alpha',
    entries:rows.map((row, i) => ({id:'e'+i, text:'Lesson '+i, status:'candidate', source:'генерация'}))}]};
  h.run('workspace.memory=memory; drawMemory();');
  rendered.push(h.element('workspaceBody').innerHTML);
  rendered.push(h.context.qualityTable([{id:'d0', service:'api', total:45, as_is:40, changed:2,
    dropped:1, open:1, waiting:1, unknown:0, followups:2, as_is_share:40/43}]));
  h.context.drawAnalytics({totals:{tasks:45, completed:40, attempts:50, failed_attempts:5,
    first_pass:35, median_seconds:90, p90_seconds:180, tokens:4500, token_coverage:50,
    cost:12.5, currency:'USD', cost_coverage:45}, groups:[{id:'d0', service:'api', tasks:45,
    attempts:50, failed_attempts:5, median_seconds:90, p90_seconds:180, tokens:4500}]});
  rendered.push(h.element('workspaceBody').innerHTML);
  for (const html of rendered) assert.doesNotMatch(html, /[А-Яа-яЁё]/);
  assert.match(rendered[3], /Price per 1M tokens/);
  assert.match(rendered[5], /Merged unchanged/);
  assert.match(rendered[6], /4,500/);
  assert.match(rendered[6], /class="state-label state-done">Completed/);
  assert.match(rendered[7], /Confirm with evidence/);
  assert.match(rendered[7], /Source: Implementation/);
  assert.match(rendered[8], /Unchanged share/);
  assert.match(rendered[9], /90th percentile/);
  assert.match(rendered[9], /12.5 USD/);
  assert.equal(h.context.minutes(90), '1.5 min');
  assert.match(h.context.fmtWhen(new Date(2020, 0, 2, 13, 5).getTime()/1000), /Jan 2/);
});

test('English UI preserves user-written task, rework, and memory content without mutation', () => {
  const h = harness('en'), row = {...records(1)[0], message:'Авторское сообщение <tag>', summary:'Описание аналитика'};
  h.context.records = [row]; h.run('stats.data={daemons:{},records};');
  const original = JSON.stringify(row);
  assert.match(h.context.renderJournal([row]), /Авторское сообщение &lt;tag>/);
  assert.match(h.context.renderProposals([{...row, result:'posted'}]), /Описание аналитика/);
  h.context.drawRequirements({control:false, rows:[{...row, request:'r1', created_at:row.finished_at,
    status:'done', note:'Изменённый контракт', error:'Особый ответ исполнителя'}]});
  assert.match(h.element('workspaceBody').innerHTML, /Изменённый контракт/);
  assert.match(h.element('workspaceBody').innerHTML, /Особый ответ исполнителя/);
  const memory = {available:true, control:false, sources:[{key:'alpha', id:'alpha', name:'Имя владельца',
    entries:[{id:'e1', status:'confirmed', text:'Конкретный урок', evidence:'Проверено вручную',
      scope:['Заказы'], source:'Пользовательский источник', verification:{reason:'Исходное доказательство'}}]}]};
  const storedMemory = JSON.stringify(memory);
  h.context.memory=memory; h.run('workspace.memory=memory; drawMemory();');
  const html = h.element('workspaceBody').innerHTML;
  for (const text of ['Имя владельца','Конкретный урок','Проверено вручную','Заказы',
    'Пользовательский источник','Исходное доказательство']) assert.ok(html.includes(text), text);
  assert.equal(JSON.stringify(row), original);
  assert.equal(JSON.stringify(memory), storedMemory);
  assert.equal(h.context.memorySourceLabel('исследование'), 'Exploration');
  assert.equal(h.context.memorySourceLabel('constructor'), 'constructor');
});

test('English rework uses server-message translation for dependency waits and failures', () => {
  const h = harness('en'), translated = [];
  h.context.translateServerMessage = message => {
    translated.push(message);
    return ({'Ожидает зависимости':'Waiting for a dependency', 'Запрос прерван':'Request interrupted'})[message] || message;
  };
  const rows = records(2).map((row, i) => ({...row, request:'r'+i, created_at:row.finished_at,
    status:i ? 'interrupted' : 'queued', note:'Requirements',
    waiting_reason:i ? '' : 'Ожидает зависимости', error:i ? 'Запрос прерван' : ''}));
  h.context.drawRequirements({control:false, rows});
  const html = h.element('workspaceBody').innerHTML;
  assert.match(html, /Waiting for a dependency/); assert.match(html, /Request interrupted/);
  assert.doesNotMatch(html, /Ожидает зависимости|Запрос прерван/);
  assert.ok(translated.includes('Ожидает зависимости')); assert.ok(translated.includes('Запрос прерван'));
});
