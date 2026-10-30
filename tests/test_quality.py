"""Качество сданных задач: ретроспектива записывает исходы, дашборд считает доли и недели."""
import contextlib
import importlib.util
import io
import json
import os
import time
from unittest import mock

from helpers import PROJECT_DIR
from test_retro import DAY, RetroBase
from jira_gigacode import retro


def _load_quality():
    path = os.path.join(PROJECT_DIR, 'office_dashboard', 'artel_dashboard', 'quality.py')
    spec = importlib.util.spec_from_file_location('artel_quality_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = _load_quality()


class OutcomeRecordTest(RetroBase):
    def run_retro(self, dry=False):
        with mock.patch.dict(os.environ, {'FAKE_RETRO': 'ok', 'FAKE_PROMPT_DIR': self.tmp}), \
                contextlib.redirect_stdout(io.StringIO()):
            return retro.run_retro(self.cfg, dry_run=dry)

    def test_merged_with_human_changes(self):
        self.deliver()
        self.human_fix_on_branch()
        self.merge()
        self.run_retro()
        o = retro.load_outcomes(self.cfg)['T-1']
        self.assertEqual((o['outcome'], o['changed'], o['human_commits']), (retro.MERGED_CHANGED, True, 1))
        self.assertEqual(o['human_lines'], 2, 'две добавленные строки')

    def test_open_task_is_recorded_too(self):
        self.deliver()
        self.run_retro()
        self.assertEqual(retro.load_outcomes(self.cfg)['T-1']['outcome'], retro.OPEN)

    def test_squash_without_differences_is_as_is(self):
        self.deliver()
        self.merge(squash=True)
        self.run_retro()
        o = retro.load_outcomes(self.cfg)['T-1']
        self.assertEqual((o['outcome'], o['changed']), (retro.SQUASHED, False))

    def test_dry_run_writes_nothing(self):
        self.deliver()
        self.merge()
        self.run_retro(dry=True)
        self.assertEqual(retro.load_outcomes(self.cfg), {})

    def test_dashboard_reads_what_retro_wrote(self):
        self.deliver('T-1', days_ago=3)
        self.human_fix_on_branch()
        self.merge()
        self.run_retro()
        self.deliver('T-2', days_ago=0)   # свежая — ещё не проверялась
        rows = {r['issue']: r for r in quality.load_rows(retro.LOGS_DIR)}
        self.assertEqual(rows['T-1']['category'], 'changed')
        self.assertEqual(rows['T-2']['category'], 'waiting')

    def test_changed_lines(self):
        self.assertEqual(retro.changed_lines(' 2 files changed, 10 insertions(+), 3 deletions(-)'), 13)
        self.assertEqual(retro.changed_lines(' 1 file changed, 1 insertion(+)'), 1)
        self.assertEqual(retro.changed_lines(''), 0)


class SummaryTest(RetroBase):
    """Дашбордная часть — на готовых файлах delivered/outcomes, без git."""

    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.tmp, 'qlogs')
        os.makedirs(self.logs)
        self.now = time.mktime((2026, 10, 14, 12, 0, 0, 0, 0, -1))   # среда

    def write(self, daemon_id, items):
        with open(os.path.join(self.logs, f'{daemon_id}-delivered.jsonl'), 'w') as f:
            for issue, days_ago, _kind, _changed, service in items:
                f.write(json.dumps({'issue': issue, 'at': self.now - days_ago * DAY, 'head': 'h-' + issue,
                                    'service': service}) + '\n')
        outcomes = {issue: {'issue': issue, 'head': 'h-' + issue, 'outcome': kind, 'changed': changed,
                            'checked_at': self.now - DAY, 'human_lines': 10 if changed else 0,
                            'followups': 1 if issue.endswith('9') else 0}
                    for issue, _d, kind, changed, _s in items if kind}
        with open(os.path.join(self.logs, f'{daemon_id}-outcomes.json'), 'w') as f:
            json.dump(outcomes, f)

    def test_categories_and_share(self):
        self.write('ci1', [('A-1', 10, 'merged', False, 'back'), ('A-2', 10, 'squashed', False, 'web'),
                           ('A-3', 9, 'merged_changed', True, 'back'), ('A-4', 9, 'dropped', False, 'back'),
                           ('A-5', 8, 'open', False, 'back'), ('A-6', 0, None, False, 'back'),
                           ('A-9', 8, 'squashed', True, 'web')])
        s = quality.summarize(quality.load_rows(self.logs), now=self.now)
        t = s['totals']
        self.assertEqual((t['as_is'], t['changed'], t['dropped'], t['open'], t['waiting']), (2, 2, 1, 1, 1))
        self.assertEqual(t['as_is_share'], 0.4, 'доля — только по задачам с исходом')
        self.assertEqual((t['followups'], t['human_lines']), (1, 20))
        by = {(r['id'], r['service']): r for r in s['by_daemon']}
        self.assertEqual(by[('ci1', 'web')]['as_is'], 1)
        self.assertEqual(by[('ci1', 'back')]['total'], 5)

    def test_redelivered_task_waits_again(self):
        self.write('ci1', [('A-1', 5, 'merged', False, None)])
        with open(os.path.join(self.logs, 'ci1-delivered.jsonl'), 'a') as f:
            f.write(json.dumps({'issue': 'A-1', 'at': self.now - DAY, 'head': 'новая-вершина'}) + '\n')
        [row] = quality.load_rows(self.logs)
        self.assertEqual(row['category'], 'waiting')

    def test_weeks_and_filters(self):
        self.write('ci1', [('A-1', 1, 'merged', False, None), ('A-2', 8, 'dropped', False, None),
                           ('A-3', 120, 'merged', False, None)])
        self.write('ci2', [('B-1', 1, 'merged_changed', True, None)])
        s = quality.summarize(quality.load_rows(self.logs), now=self.now)
        self.assertEqual(len(s['weeks']), 12)
        starts = [w['start'] for w in s['weeks']]
        self.assertTrue(all(time.localtime(x).tm_wday == 0 and time.localtime(x).tm_hour == 0 for x in starts), 'с понедельника')
        self.assertEqual((s['weeks'][-1]['as_is'], s['weeks'][-1]['changed']), (1, 1))
        self.assertEqual(s['weeks'][-2]['dropped'], 1)
        self.assertEqual(s['totals']['total'], 4, 'итоги — за весь период, даже старше 12 недель')
        only = quality.summarize(quality.load_rows(self.logs), daemon_id='ci2', now=self.now)
        self.assertEqual(only['totals']['total'], 1)
        recent = quality.summarize(quality.load_rows(self.logs), since=self.now - 2 * DAY, now=self.now)
        self.assertEqual((recent['totals']['total'], len(recent['weeks'])), (2, 1))
        self.assertEqual(recent['last_check'], self.now - DAY)

    def test_empty(self):
        s = quality.summarize([], now=self.now)
        self.assertIsNone(s['totals']['as_is_share'])
        self.assertIsNone(s['last_check'])
