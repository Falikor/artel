"""Synthetic JSONL fixtures based on the corporate v26.9.64 schema supplied by user."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from jira_gigacode import cli_events as ce, gigacode, runtime
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office_dashboard'))


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.reporter = SimpleNamespace(path=str(Path(self.tmp.name)/'one-state.json'), set_cli=lambda x: None)
        self.execution = ce.Execution(self.reporter, 'T-1', 'generation')
        self.addCleanup(lambda: self.execution.finish('success',0))
        self.parser = ce.Parser(self.execution)

    def feed(self, **event):
        self.parser.feed((json.dumps(dict(session_id='root', **event), ensure_ascii=False)+'\n').encode())

    def test_chunks_tools_nested_and_final(self):
        raw=(json.dumps({'type':'system','subtype':'init','session_id':'root'})+'\n'+json.dumps({'type':'assistant','session_id':'root','message':{'content':[
            {'type':'thinking','thinking':'private reasoning'},
            {'type':'tool_use','id':'t1','name':'read_file','input':{'path':'тест\u2028file','token':'sensitive'}},
            {'type':'tool_use','id':'t2','name':'run_shell_command','input':{'command':'pytest'}}]}}, ensure_ascii=False)+'\n').encode()
        for byte in raw: self.parser.feed(bytes([byte]))
        self.feed(type='user',message={'content':[{'type':'tool_result','tool_use_id':'t1','is_error':False,'content':'source code'}, {'type':'tool_result','tool_use_id':'t2','is_error':True,'content':'failed test'}]})
        self.feed(type='result',parent_tool_use_id='t2',subtype='success',is_error=False,result='WRONG FINAL')
        self.assertFalse(self.parser.result_seen)
        self.feed(type='result',subtype='success',is_error=False,result='answer\nCODE_GENERATION_SUCCESS',usage={'input_tokens':5,'output_tokens':2,'cache_read_input_tokens':1})
        self.execution.flush()
        owner=ce.read_events(self.tmp.name,'one')
        self.assertNotIn('private reasoning',json.dumps(owner))
        self.assertNotIn('sensitive',json.dumps(owner))
        self.assertIn('source code',json.dumps(owner))
        self.assertEqual([e['toolUseId'] for e in owner['events'] if e['kind']=='tool_finished'],['t1'])
        self.assertIn('tool_error',[e['kind'] for e in owner['events']])
        self.assertTrue(self.parser.final_text().endswith('CODE_GENERATION_SUCCESS'))
        self.assertNotIn('WRONG FINAL', self.parser.final_text())
        self.assertFalse(self.parser.invalid)

    def test_bounded_buffers_malformed_and_no_newline(self):
        self.parser.feed(b'x'*(ce.MAX_LINE+1))
        self.assertLess(len(self.parser.buffer),ce.MAX_LINE)
        self.parser.feed(b'\nnot json\n')
        self.parser.feed(b'{"type":"result","subtype":"success","is_error":false,"result":"OK"}',final=True)
        self.assertTrue(self.parser.result_seen); self.assertTrue(self.parser.invalid)
        for _ in range(ce.MAX_EVENTS+10): self.execution.emit('tool_started','test')
        self.execution.flush()
        snapshot=ce.read_events(self.tmp.name,'one')
        self.assertEqual(len(snapshot['events']),ce.MAX_EVENTS)
        self.assertGreater(snapshot['firstSeq'],1)

    def test_real_process_events_before_exit_and_failure_modes(self):
        script=Path(self.tmp.name)/'cli'
        script.write_text('''#!/usr/bin/env python3
import json,sys,time
from pathlib import Path
sys.stdin.read()
print(json.dumps(dict(type='system',subtype='init',session_id='root')),flush=True)
print(json.dumps(dict(type='assistant',session_id='root',message={'content':[{'type':'tool_use','id':'one','name':'read_file','input':{'path':'a.py'}}]})),flush=True)
release = Path(__file__).with_name('release')
deadline = time.monotonic() + 10
while not release.exists() and time.monotonic() < deadline:
    time.sleep(.02)
if '--network-error' in sys.argv:
    print('TypeError: fetch failed',file=sys.stderr);sys.exit(1)
if '--no-result' not in sys.argv:
    print(json.dumps(dict(type='result',session_id='root',subtype='success',is_error=False,result='CODE_GENERATION_SUCCESS')),flush=True)
'''); script.chmod(0o700)
        results=[]
        with patch.object(runtime,'state',self.reporter),patch.object(runtime,'running'),patch.object(gigacode,'cli_log_path',return_value=str(Path(self.tmp.name)/'final.log')):
            worker=threading.Thread(target=lambda:results.append(gigacode.run_cli('T-1',str(script),'prompt',self.tmp.name,10)))
            worker.start()
            try:
                deadline=time.monotonic()+5
                seen=False
                while time.monotonic()<deadline:
                    snapshot=ce.read_events(self.tmp.name,'one')
                    if any(e['kind']=='tool_started' for e in snapshot['events']): seen=True; break
                    time.sleep(.05)
                self.assertTrue(seen); self.assertTrue(worker.is_alive())
            finally:
                script.with_name('release').write_text('continue')
                worker.join(12)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0],(0,'CODE_GENERATION_SUCCESS'))
            for flags in (['--network-error'],['--no-result']):
                code,output=gigacode.run_cli('T-1',str(script),'prompt',self.tmp.name,5,extra_args=flags)
                self.assertNotEqual(code,0)
                if flags==['--network-error']: self.assertIn('fetch failed',output)
            script.with_name('release').unlink()
            with patch.object(runtime,'running',False):
                code,_=gigacode.run_cli('T-1',str(script),'prompt',self.tmp.name,5)
                self.assertIsNone(code)
            self.assertEqual(ce.read_events(self.tmp.name,'one')['cli']['status'],'interrupted')

    def test_parallel_execution_isolation(self):
        other=ce.Execution(SimpleNamespace(path=str(Path(self.tmp.name)/'two-state.json'),set_cli=lambda x:None),'T-2','review')
        try:
            self.execution.emit('tool_started','first',{'input':'one'})
            other.emit('tool_started','second',{'input':'two'})
            self.execution.flush();other.flush()
            a,b=(ce.read_events(self.tmp.name,i) for i in ('one','two'))
            self.assertNotEqual(a['executionId'],b['executionId'])
            self.assertNotIn('second',json.dumps(a));self.assertNotIn('first',json.dumps(b['events']))
        finally: other.finish('success',0)

class StreamAccessTest(unittest.TestCase):
    def test_logs_without_login_reconnect_and_wrong_execution(self):
        import http.client
        from artel_dashboard.handler import make_server
        from artel_dashboard.stores import Names, Prices, Characters
        with tempfile.TemporaryDirectory() as tmp:
            stores=[cls(str(Path(tmp)/name)) for cls,name in ((Names,'names.json'),(Prices,'prices.json'),(Characters,'characters.json'))]
            server=make_server('127.0.0.1',0,tmp,tmp,*stores)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            execution=ce.Execution(SimpleNamespace(path=str(Path(tmp)/'test-state.json'),set_cli=lambda x:None),'T-1','generation')
            try:
                execution.emit('tool_started','Анализирует исходный код',{'path':'confidential.py'})
                execution.flush()
                def request(path,method='GET',headers=None):
                    connection=http.client.HTTPConnection(*server.server_address,timeout=3)
                    connection.request(method,path,headers=headers or {})
                    return connection,connection.getresponse()
                def snapshot(headers=None):
                    c,r=request('/api/cli-events?id=test',headers=headers)
                    try:
                        self.assertEqual(r.status,200)
                        for _ in range(6):
                            line=r.readline().decode()
                            if line.startswith('data: '): return json.loads(line[6:])
                        self.fail('Missing SSE snapshot')
                    finally: c.close()
                public=snapshot()
                self.assertIn('confidential.py',json.dumps(public))
                c,r=request('/api/names');self.assertEqual(r.status,200);r.read();c.close()
                c,r=request('/api/state');state=json.loads(r.read());c.close()
                self.assertTrue(state['control']);self.assertNotIn('owner',state)
                c,r=request('/api/owner-session','POST')
                self.assertEqual(r.status,404);r.read();c.close()
                c,r=request('/api/names','POST',{'Origin':'https://evil.example'})
                self.assertEqual(r.status,403);r.read();c.close()
                execution.emit('tool_finished','Инструмент завершил работу');execution.flush()
                again=snapshot({'Last-Event-ID':public['executionId']+':'+str(public['lastSeq'])})
                self.assertGreater(again['lastSeq'],public['lastSeq']);self.assertFalse(again['reset'])
                self.assertTrue(snapshot({'Last-Event-ID':'another-run:99'})['reset'])
            finally:
                execution.finish('success',0);server.maintenance_paused=True
                server.shutdown();server.server_close();thread.join(3)
