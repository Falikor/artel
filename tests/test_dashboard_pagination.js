'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const scripts = path.join(__dirname, '../office_dashboard/static/js');
function harness() {
  const elements = new Map(), listeners = new Map(), focus = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value: id === 'workspaceDays' ? '30' : '', innerHTML: '',
      querySelectorAll: () => [], querySelector: () => null, setAttribute() {},
      focus: options => focus.push({id, options}),
      addEventListener(type, listener) { const key = id + ':' + type; if (!listeners.has(key)) listeners.set(key, []); listeners.get(key).push(listener); }});
    return elements.get(id);
  };
  const context = vm.createContext({Date, URLSearchParams, setTimeout, clearTimeout, setInterval, clearInterval,
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
