"""Статистика по задачам Jira, а не по запускам; предложения в простое."""
import contextlib
import io
import json
import os
import socket
import threading
import time
import urllib.request
from unittest import mock

from helpers import DaemonTestCase
from test_dashboard_data import _load_server
from test_explore import ExploreBase
from jira_gigacode import explore, runtime


def run(issue, result, finished, tokens=None, daemon='ci1', **extra):
    return dict({'id': daemon, 'issue': issue, 'result': result, 'started_at': finished - 600, 'finished_at': finished,
                 'gen_seconds': 300, 'total_seconds': 600, 'tokens': tokens}, **extra)


class GroupTasksTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def test_failures_then_success_is_one_success(self):
        [task] = self.srv.group_tasks([
            run('T-1', 'fail', 1000, {'input': 100, 'output': 10, 'cached': 0, 'total': 110}, message='GigaCode упал'),
            run('T-1', 'fail', 2000, {'input': 200, 'output': 20, 'cached': 50, 'total': 220}),
            run('T-1', 'ok', 3000, {'input': 300, 'output': 30, 'cached': 0, 'total': 330}, stand='dev', branch='b'),
        ])
        self.assertEqual((task['result'], task['attempts'], task['failed_attempts']), ('ok', 3, 2))
        self.assertEqual(task['tokens'], {'total': 660, 'input': 600, 'output': 60, 'cached': 50})
        self.assertEqual((task['gen_seconds'], task['total_seconds']), (900, 1800))
        self.assertEqual((task['started_at'], task['finished_at']), (400, 3000))
        self.assertEqual((task['stand'], task['branch'], task['message']), ('dev', 'b', None))
        self.assertEqual([r['result'] for r in task['runs']], ['fail', 'fail', 'ok'])

    def test_result_is_the_last_attempt(self):
        [task] = self.srv.group_tasks([run('T-1', 'ok', 1000), run('T-1', 'fail', 2000, message='снова в работе, упал')])
        self.assertEqual((task['result'], task['message']), ('fail', 'снова в работе, упал'))

    def test_daemons_and_issues_are_separate(self):
        tasks = self.srv.group_tasks([run('T-1', 'ok', 1), run('T-2', 'ok', 2), run('T-1', 'ok', 3, daemon='ci2')])
        self.assertEqual(sorted((t['id'], t['issue']) for t in tasks), [('ci1', 'T-1'), ('ci1', 'T-2'), ('ci2', 'T-1')])

    def test_mixed_token_detail(self):
        [task] = self.srv.group_tasks([run('T-1', 'fail', 1, {'total': 50, 'input': None, 'output': None}),
                                       run('T-1', 'ok', 2, {'input': 80, 'output': 20, 'cached': 0, 'total': 100})])
        self.assertEqual(task['tokens']['total'], 150)
        self.assertIsNone(task['tokens']['input'], 'не все попытки сообщили вход/выход')
        prices = {'input': 10, 'output': 20, 'cached': 1, 'currency': '₽'}
        cost, estimate = self.srv.runs_cost(task, prices)
        self.assertAlmostEqual(cost, (50 * 10 + 80 * 10 + 20 * 20) / 1e6, msg='стоимость — сумма по попыткам')
        self.assertTrue(estimate)

    def test_period_counts_task_with_all_attempts(self):
        logs = os.path.join(self.tmp, 'logs')
        os.makedirs(logs)
        now = time.time()
        with open(os.path.join(logs, 'ci1-history.jsonl'), 'w') as f:
            for r in (run('T-1', 'fail', now - 10 * 86400), run('T-1', 'ok', now - 3600), run('T-2', 'ok', now - 20 * 86400)):
                r.pop('id')
                f.write(json.dumps(r) + '\n')
        [task] = self.srv.read_tasks(logs, since=now - 86400)
        self.assertEqual((task['issue'], task['attempts']), ('T-1', 2), 'попытка до периода тоже учтена')


class HttpTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.tmp, 'logs')
        os.makedirs(self.logs)
        now = time.time()
        with open(os.path.join(self.logs, 'ci1-history.jsonl'), 'w') as f:
            for r in (run('T-1', 'fail', now - 7200), run('T-1', 'fail', now - 3600),
                      run('T-1', 'ok', now - 60, {'input': 1_000_000, 'output': 0, 'cached': 0, 'total': 1_000_000})):
                r.pop('id')
                f.write(json.dumps(r) + '\n')
        with open(os.path.join(self.logs, 'ci1-proposals.jsonl'), 'w') as f:
            f.write(json.dumps({'issue': 'T-50', 'result': 'posted', 'finished_at': now - 30, 'comment_id': '777'}) + '\n')
            f.write(json.dumps({'issue': 'T-51', 'result': 'posted', 'finished_at': now - 40 * 86400}) + '\n')
            f.write('мусор\n')
        with open(os.path.join(self.logs, 'ci1-state.json'), 'w') as f:
            json.dump({'project': 'T', 'pid': os.getpid(), 'host': socket.gethostname(), 'stage': 'idle',
                       'heartbeat': now, 'ci_id': '3191860'}, f)
        prices = self.srv.Prices(os.path.join(self.tmp, 'prices.json'))
        prices.save({'input': 10, 'output': 0, 'cached': 0, 'currency': '₽'})
        httpd = self.srv.make_server('127.0.0.1', 0, self.logs, self.tmp, self.srv.Names(os.path.join(self.tmp, 'n.json')),
                                     prices, None)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.base = f'http://127.0.0.1:{httpd.server_address[1]}'

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as resp:
            return resp.read()

    def test_history_is_by_task(self):
        data = json.loads(self.get('/api/history?days=7'))
        [task] = data['records']
        self.assertEqual((task['issue'], task['result'], task['attempts']), ('T-1', 'ok', 3))
        self.assertEqual([p['issue'] for p in data['proposals']], ['T-50'], 'предложения за период, без мусора')
        self.assertEqual(data['proposals'][0]['id'], 'ci1')

    def test_csv_row_per_task(self):
        lines = self.get('/api/history.csv?days=7').decode('utf-8-sig').splitlines()
        self.assertIn('Попыток;Неудачных', lines[0])
        self.assertEqual(len(lines), 2)
        self.assertIn('T-1;готово;3;2;', lines[1])
        self.assertIn(';10,00;', lines[1])


class CardCountersTest(DaemonTestCase):
    def test_counters_count_tasks_not_runs(self):
        import daemon_state
        rep = daemon_state.StateReporter(os.path.join(self.tmp, 't-state.json'), 'T')
        try:
            for issue, ok in (('T-1', False), ('T-1', False), ('T-1', True), ('T-2', False)):
                rep.emit('generating', issue)
                rep.finish_issue(issue, ok)
            c = rep.state['counters']
            self.assertEqual((c['done'], c['failed'], c['attempts']), (1, 1, 4))
        finally:
            rep.close()


class ProposalLedgerTest(ExploreBase):
    """Каждый прогон исследования записывается в logs/{КЭ}-proposals.jsonl."""

    def ledger(self):
        path = explore.proposals_path(self.cfg)
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            return [json.loads(line) for line in f]

    def test_posted_with_comment_id(self):
        self.idle()
        [rec] = self.ledger()
        self.assertEqual((rec['issue'], rec['result']), ('T-7', 'posted'))
        self.assertEqual(rec['comment_id'], str(len(self.jira.posted_comments)))
        self.assertTrue(rec['summary'])
        self.assertGreaterEqual(rec['seconds'], 0)

    def test_empty_result(self):
        self.idle(mode='empty')
        self.assertEqual([r['result'] for r in self.ledger()], ['empty'])

    def test_dry_run_not_recorded(self):
        with mock.patch.object(runtime, 'DRY_RUN', True), contextlib.redirect_stdout(io.StringIO()):
            self.idle()
        self.assertEqual(self.ledger(), [])
