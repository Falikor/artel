"""Isolated UI review server: 40 fake daemons, real local storage/API, no external calls.
Run from repository root: python3 tests/ui_preview.py [--port 8879]
All mutable data lives under a new temporary directory. Never starts actual daemons.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'office_dashboard'))
from daemon_state import StateReporter
from artel_dashboard import common, features, knowledge
from artel_dashboard.handler import make_server,Handler
from artel_dashboard.stores import Names,Prices,Characters
from jira_gigacode import supervisor, cli_events, memory_store, retry_control, requirements_rework
from demo import backfill_history, backfill_quality, backfill_proposals


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8879);args=parser.parse_args()
    folder=Path(tempfile.mkdtemp(prefix='artel-ui-review-'));common.DEFAULT_LOGS=str(folder)
    configs=[];reporters=[]
    projects=['CORE','WEB','API','OPS'];names=['Алексей','Анна','Михаил','Мария','Павел','Елена','Денис','Ольга','Илья','Наталья']
    for i in range(40):
        ident='ci'+str(100+i);project=projects[i//10]
        cfg={'general':{'ci_id':str(100+i),'repo_path':str(folder)},'jira':{'project':project},'memory':{'path':str(folder/(ident+'.md'))}}
        configs.append({'name':ident,'config':cfg})
        r=StateReporter(str(folder/(ident+'-state.json')),project,name=names[i%10],ci_id=str(100+i),heartbeat_sec=3,daemon_version='2.22.0',poll_interval=60)
        r.state['features']=['poke','stop','feature-control','task-dependencies','cli-events']
        r.emit(['generating','reviewing','idle','idle','error','polling','rework','idle','success','stopped'][i%10],issue=project+'-'+str(i+101))
        reporters.append(r)
        for backfill,suffix in [(backfill_history,'history'),(backfill_quality,'quality'),(backfill_proposals,'proposals')]:
            backfill(str(folder),ident.upper(),i)
        (folder/(ident+'-agent.log')).write_text('2026-10-30 09:00:00 - INFO - ['+project+'-101] Выполняется проверка результата\n',encoding='utf-8')
    def load_configs():return configs
    supervisor.load_configs=load_configs;features.load_configs=load_configs;knowledge.load_configs=load_configs
    entries=[memory_store._entry('Перед изменением API проверь обратную совместимость контрактов.','CORE-101','ретроспектива',time.time()),memory_store._entry('При добавлении нового маршрута обнови интеграционные тесты.','CORE-104','ревью',time.time())]
    entries[0].update(needs_review=True,verification={'result':'disputed','reason':'Требуется уточнить область применения'},scope=['api'])
    entries[1].update(status='confirmed',evidence='Проверено в тестах маршрутизации',scope=['routing'])
    (folder/'ci100.md.store.json').write_text(json.dumps({'version':1,'entries':entries,'legacy_imported':True},ensure_ascii=False))
    retry_control.decide(retry_control.path_for(folder,'ci100'),'CORE-105','pause',3600)
    requirements_rework.submit(str(folder),'ci100',configs[0]['config'],'CORE-101','Уточнить обработку пустого ответа API')
    ex=cli_events.Execution(reporters[0],'CORE-101','generation');stream=cli_events.Parser(ex)
    for event in [dict(type='system',subtype='init',model='Тестовый агент'),dict(type='assistant',message={'content':[{'type':'tool_use','id':'read-1','name':'read_file','input':{'path':'src/api/contracts.py'}}]}),dict(type='user',message={'content':[{'type':'tool_result','tool_use_id':'read-1','is_error':False,'content':'Контракт ответа: status, data, metadata.'}]}),dict(type='assistant',message={'content':[{'type':'tool_use','id':'shell-1','name':'run_shell_command','input':{'command':'python -m unittest tests.test_contracts'}}]}),dict(type='user',message={'content':[{'type':'tool_result','tool_use_id':'shell-1','is_error':False,'content':'Ran 12 tests. OK'}]}),dict(type='result',subtype='success',is_error=False,result='Проверки завершены. CODE_GENERATION_SUCCESS')]:
        stream.feed((json.dumps(dict(event,session_id='preview'))+'\n').encode())
    ex.finish('success',0)
    names=Names(str(folder/'names.json'));prices=Prices(str(folder/'prices.json'));characters=Characters(str(folder/'characters.json'))
    server=make_server('127.0.0.1',args.port,str(folder),common.DEFAULT_ASSETS,names,prices,characters)
    # Control is simulated in this process; cannot signal a real daemon or supervisor.
    def stop(self,ident):
        r=next((r for r in reporters if Path(r.path).name==ident+'-state.json'),None)
        if r:r.emit('stopped');return {'ok':True}
        return {'ok':False,'reason':'unknown'}
    def start(self,ident):
        r=next((r for r in reporters if Path(r.path).name==ident+'-state.json'),None)
        if r:r.emit('idle');return {'ok':True}
        return {'ok':False,'reason':'unknown'}
    Handler.stop=stop;Handler.start=start
    print('UI preview: http://127.0.0.1:'+str(args.port)+'; temporary data: '+str(folder),flush=True)
    try:server.serve_forever()
    finally:
        server.maintenance_paused=True;server.server_close()
        for r in reporters:r.close()

if __name__=='__main__':main()
