"""Данные дашборда: цены и стоимость задач, простой с последней задачи, КЭ, сервис и кэш в истории."""
import importlib.util
import json
import os
import socket
import threading
import time
import urllib.request

from helpers import PROJECT_DIR, DaemonTestCase


def _load_server():
    path = os.path.join(PROJECT_DIR, 'office_dashboard', 'server.py')
    spec = importlib.util.spec_from_file_location('artel_dashboard_server_data', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CostTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def test_cost_with_cache(self):
        prices = {'input': 60, 'output': 240, 'cached': 15, 'currency': '₽'}
        cost, estimate = self.srv.task_cost({'input': 149487, 'output': 19880, 'cached': 42744, 'total': 169367}, prices)
        self.assertAlmostEqual(cost, (106743 * 60 + 42744 * 15 + 19880 * 240) / 1e6)
        self.assertFalse(estimate)

    def test_total_only_is_estimate(self):
        cost, estimate = self.srv.task_cost({'total': 1_000_000}, {'input': 50, 'output': 0, 'cached': 0})
        self.assertEqual((cost, estimate), (50.0, True))

    def test_no_prices_or_tokens(self):
        self.assertEqual(self.srv.task_cost({'total': 10}, {'input': 0, 'output': 0, 'cached': 0}), (None, False))
        self.assertEqual(self.srv.task_cost(None, {'input': 1, 'output': 1, 'cached': 1}), (None, False))

    def test_cache_bigger_than_input_is_clamped(self):
        cost, _ = self.srv.task_cost({'input': 100, 'output': 0, 'cached': 500}, {'input': 1e6, 'output': 0, 'cached': 1e6})
        self.assertEqual(cost, 100.0)

    def test_prices_store(self):
        store = self.srv.Prices(os.path.join(self.tmp, 'prices.json'))
        self.assertEqual(store.load()['currency'], '₽')
        saved = store.save({'input': '1,5', 'output': 3, 'cached': '0', 'currency': '$'})
        self.assertEqual(saved, {'input': 1.5, 'output': 3.0, 'cached': 0.0, 'currency': '$'})
        self.assertEqual(store.load(), saved)
        for bad in ({'input': 'много'}, {'input': -1}):
            with self.assertRaises(ValueError):
                store.save(bad)


class ServerDataTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.tmp, 'logs')
        os.makedirs(self.logs)
        self.names = self.srv.Names(os.path.join(self.tmp, 'names.json'))
        self.prices = self.srv.Prices(os.path.join(self.tmp, 'prices.json'))

    def state(self, key, **extra):
        data = {'project': 'HRPPA', 'pid': os.getpid(), 'host': socket.gethostname(), 'stage': 'idle',
                'heartbeat': time.time(), 'started_at': time.time() - 7200}
        data.update(extra)
        with open(os.path.join(self.logs, f'{key}-state.json'), 'w') as f:
            json.dump(data, f)

    def history(self, key, *records):
        with open(os.path.join(self.logs, f'{key}-history.jsonl'), 'a') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')

    def daemon(self, key):
        return next(d for d in self.srv.read_all(self.logs, self.names)['daemons'] if d['id'] == key)

    def test_two_ci_in_one_project_are_separate(self):
        self.state('ci3191860', ci_id='3191860')
        self.state('ci15172563', ci_id='15172563')
        ids = sorted(d['id'] for d in self.srv.read_all(self.logs)['daemons'])
        self.assertEqual(ids, ['ci15172563', 'ci3191860'])
        self.assertEqual(self.daemon('ci3191860')['ci_id'], '3191860')

    def test_last_task_from_history(self):
        self.state('ci1', ci_id='1')
        self.assertIsNone(self.daemon('ci1')['last_task'], 'задач ещё не было — простой с запуска')
        self.history('ci1', {'issue': 'T-1', 'finished_at': 100.0, 'result': 'ok'},
                     {'issue': 'T-2', 'finished_at': 200.0, 'result': 'fail'}, 'мусорная строка')
        self.assertEqual(self.daemon('ci1')['last_task'], {'issue': 'T-2', 'finished_at': 200.0, 'result': 'fail'})

    def test_fresh_last_result_beats_history(self):
        self.state('ci1', last_result={'issue': 'T-9', 't': 300.0, 'result': 'ok'})
        self.history('ci1', {'issue': 'T-2', 'finished_at': 200.0, 'result': 'ok'})
        self.assertEqual(self.daemon('ci1')['last_task']['issue'], 'T-9')

    def test_history_tail_cache_updates(self):
        self.state('ci1')
        self.history('ci1', {'issue': 'T-1', 'finished_at': 100.0})
        self.assertEqual(self.daemon('ci1')['last_task']['issue'], 'T-1')
        time.sleep(0.01)
        self.history('ci1', {'issue': 'T-2', 'finished_at': 150.0})
        self.assertEqual(self.daemon('ci1')['last_task']['issue'], 'T-2')

    def test_csv_has_ci_service_and_cost(self):
        self.state('ci1', ci_id='3191860', name='Олег')
        self.history('ci1', {'id': 'ci1', 'issue': 'T-1', 'finished_at': time.time(), 'result': 'ok', 'service': 'web',
                             'tokens': {'input': 1_000_000, 'output': 0, 'cached': 0, 'total': 1_000_000}})
        self.prices.save({'input': 10, 'output': 20, 'cached': 1, 'currency': '₽'})
        httpd = self.srv.make_server('127.0.0.1', 0, self.logs, self.tmp, self.names, self.prices, None)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f'http://127.0.0.1:{httpd.server_address[1]}'
        with urllib.request.urlopen(f'{base}/api/history.csv?days=1', timeout=5) as resp:
            lines = resp.read().decode('utf-8-sig').splitlines()
        self.assertIn('Стоимость, ₽', lines[0])
        self.assertIn('КЭ 3191860;web;T-1', lines[1])
        self.assertIn(';10,00;', lines[1])
        req = urllib.request.Request(f'{base}/api/prices', method='POST', headers={'Content-Type': 'application/json'},
                                     data=json.dumps({'input': 'x'}).encode())
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertIn('error', json.loads(resp.read()))
        with urllib.request.urlopen(f'{base}/api/prices', timeout=5) as resp:
            self.assertEqual(json.loads(resp.read())['input'], 10.0)


class HistoryRecordTest(DaemonTestCase):
    def test_service_and_cached_tokens_in_history(self):
        import daemon_state
        path = os.path.join(self.tmp, 't-state.json')
        rep = daemon_state.StateReporter(path, 'T', ci_id='42', daemon_version='9')
        try:
            rep.emit('generating', 'T-1', service='web')
            rep.note_tokens('T-1', {'input': 10, 'output': 5, 'cached': 4, 'total': 15, 'source': 'text'})
            rep.finish_issue('T-1', True)
        finally:
            rep.close()
        with open(os.path.join(self.tmp, 't-history.jsonl'), encoding='utf-8') as f:
            record = json.loads(f.readline())
        self.assertEqual(record['service'], 'web')
        self.assertEqual(record['tokens']['cached'], 4)
        with open(path, encoding='utf-8') as f:
            self.assertEqual(json.load(f)['ci_id'], '42')


class CharactersTest(DaemonTestCase):
    """Персонаж демона: выбор на дашборде → конфиг → автоматика (стабильная, без повторов, пока хватает)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def setUp(self):
        super().setUp()
        self.store = self.srv.Characters(os.path.join(self.tmp, 'characters.json'))

    def resolve(self, *daemons):
        ds = [dict(d) for d in daemons]
        self.store.resolve(ds)
        return {d['id']: (d['character'], d['character_source']) for d in ds}

    def test_auto_is_unique_and_stable(self):
        first = self.resolve({'id': 'ci1'}, {'id': 'ci2'}, {'id': 'ci3'})
        self.assertEqual(len({c for c, _ in first.values()}), 3, 'без повторов, пока персонажей хватает')
        self.assertTrue(all(src == 'auto' for _, src in first.values()))
        # Появился новый демон и пропал старый — у остальных персонаж не меняется
        again = self.resolve({'id': 'ci0'}, {'id': 'ci2'}, {'id': 'ci3'})
        self.assertEqual(again['ci2'], first['ci2'])
        self.assertEqual(again['ci3'], first['ci3'])
        self.assertNotIn(again['ci0'][0], {first['ci2'][0], first['ci3'][0], first['ci1'][0]})

    def test_more_daemons_than_characters(self):
        result = self.resolve(*[{'id': f'ci{i}'} for i in range(10)])
        self.assertEqual(len(result), 10)
        self.assertEqual(len({c for c, _ in result.values()}), len(self.store.available))

    def test_priority(self):
        self.assertEqual(self.resolve({'id': 'ci1', 'character': 'manager_navy'})['ci1'], ('manager_navy', 'config'))
        self.store.set('ci1', 'worker_blond_blue')
        self.assertEqual(self.resolve({'id': 'ci1', 'character': 'manager_navy'})['ci1'], ('worker_blond_blue', 'dashboard'))
        self.store.set('ci1', None)
        self.assertEqual(self.resolve({'id': 'ci1', 'character': 'manager_navy'})['ci1'], ('manager_navy', 'config'))

    def test_unknown_config_character(self):
        ds = [{'id': 'ci1', 'character': 'worker_pink'}]
        self.store.resolve(ds)
        self.assertEqual(ds[0]['character_source'], 'auto')
        self.assertIn('worker_pink', ds[0]['character_warning'])

    def test_validation_and_persistence(self):
        with self.assertRaises(ValueError):
            self.store.set('ci1', 'нет-такого')
        self.store.set('ci1', 'worker_brown_red')
        again = self.srv.Characters(self.store.path)
        self.assertEqual(again.load()['ci1'], {'character': 'worker_brown_red', 'source': 'user'})

    def test_http_and_read_all(self):
        logs = os.path.join(self.tmp, 'logs')
        os.makedirs(logs)
        with open(os.path.join(logs, 'ci1-state.json'), 'w') as f:
            json.dump({'project': 'T', 'pid': os.getpid(), 'host': socket.gethostname(), 'stage': 'idle',
                       'heartbeat': time.time(), 'character': 'manager_navy'}, f)
        names = self.srv.Names(os.path.join(self.tmp, 'names.json'))
        self.assertEqual(self.srv.read_all(logs, names, self.store)['daemons'][0]['character'], 'manager_navy')
        httpd = self.srv.make_server('127.0.0.1', 0, logs, self.tmp, names, None, self.store, control=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)

        def post(payload, endpoint='characters'):
            req = urllib.request.Request(f'http://127.0.0.1:{httpd.server_address[1]}/api/{endpoint}', method='POST',
                                         headers={'Content-Type': 'application/json'}, data=json.dumps(payload).encode())
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        self.assertIn('error', post({'id': 'ci1', 'character': 'нет'}))
        self.assertTrue(post({'id': 'ci1', 'character': 'worker_dark_purple'})['ok'], 'работает и в режиме --no-control')
        self.assertEqual(self.srv.read_all(logs, names, self.store)['daemons'][0]['character_source'], 'dashboard')
        with urllib.request.urlopen(f'http://127.0.0.1:{httpd.server_address[1]}/api/state') as resp:
            json.load(resp)
        moved = post({'id': 'ci1', 'name': 'Поиск'}, 'offices')
        self.assertTrue(moved['daemons'][0]['office_manual'])
        self.assertIn('Поиск', moved['daemons'][0]['office_title'])
        self.assertIn('error', post({'id':'ci1', 'room':'missing'}, 'offices'))
        room = moved['daemons'][0]['office_id']
        renamed = post({'action':'rename','room':room,'name':'Лаборатория'}, 'offices')
        self.assertEqual(renamed['daemons'][0]['office_title'], 'Лаборатория')
        self.assertIn('error', post({'action':'delete','room':room}, 'offices'))
        post({'id':'ci1','room':'auto'}, 'offices')
        deleted = post({'action':'delete','room':room}, 'offices')
        self.assertNotIn(room, {r['id'] for r in deleted['offices']})
        self.assertEqual(post({'id':'ci1','issue':'T-1','action':'block'}, 'retries')['reason'], 'readonly')
        httpd.control = True
        self.assertTrue(post({'id':'ci1','issue':'T-1','action':'block'}, 'retries')['ok'])
        with urllib.request.urlopen(f'http://127.0.0.1:{httpd.server_address[1]}/api/retries?id=ci1') as resp:
            self.assertEqual(json.load(resp)['T-1']['mode'], 'blocked')

    def test_daemon_passes_config_character(self):
        from unittest import mock
        from jira_gigacode import runtime
        with mock.patch.object(runtime, 'LOGS_DIR', self.tmp):
            rep = runtime.create_state_reporter({'jira': {'project': 'T'}, 'general': {'character': 'manager_navy', 'service': 'backend', 'office_group': 'Payments'}}, None, 60)
        try:
            self.assertEqual(rep.state['character'], 'manager_navy')
            self.assertEqual(rep.state['service'], 'backend')
            self.assertEqual(rep.state['office_group'], 'Payments')
        finally:
            rep.close()
