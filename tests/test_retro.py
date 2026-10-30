"""Ретроспектива: что стало со сданными задачами (git + Jira), разбор агентом, уроки, расписание."""
import contextlib
import io
import os
import time
from unittest import mock

from helpers import DaemonTestCase, git, read_text
from jira_gigacode import experience, issue_report, pipeline, retro, runtime

BR = 'feature/ai_team/T-1'
DAY = 86400


class RetroBase(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)
        for name, value in (('LOGS_DIR', os.path.join(self.tmp, 'logs')), ('PROJECT_DIR', self.tmp)):
            p = mock.patch.object(retro, name, value)
            p.start()
            self.addCleanup(p.stop)

    def commit(self, name, text, message, author=None):
        with open(os.path.join(self.work, name), 'w') as f:
            f.write(text)
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-qm', message, *([f'--author={author}'] if author else []))

    def deliver(self, key='T-1', days_ago=3):
        """Как демон: ветка от develop с работой агента, запушена и записана в журнал сдачи."""
        git(self.work, 'checkout', '-qB', BR, 'origin/develop')
        self.commit('feature.py', 'def f(x):\n    return x.value\n', f'{key}: Automated code generation via AI')
        git(self.work, 'push', '-q', '-f', 'origin', BR)
        issue_report.report_start(key)
        issue_report.report_set(key, branch=BR, base='origin/develop', head=git(self.work, 'rev-parse', 'HEAD'),
                                base_sha=git(self.work, 'rev-parse', 'origin/develop'))
        with mock.patch.object(retro.time, 'time', return_value=time.time() - days_ago * DAY):
            retro.record_delivery(key, self.cfg)
        git(self.work, 'checkout', '-q', 'develop')
        return retro.load_deliveries(self.cfg)[key]

    def human_fix_on_branch(self):
        git(self.work, 'checkout', '-q', BR)
        self.commit('feature.py', 'def f(x):\n    if x is None:\n        return None\n    return x.value\n',
                    'Проверка на None', author='Человек <human@example.com>')
        git(self.work, 'push', '-q', 'origin', BR)
        git(self.work, 'checkout', '-q', 'develop')

    def merge(self, squash=False):
        git(self.work, 'checkout', '-q', 'develop')
        git(self.work, 'pull', '-q', 'origin', 'develop')
        git(self.work, 'fetch', '-q', 'origin')
        if squash:
            git(self.work, 'merge', '--squash', f'origin/{BR}')
            git(self.work, 'commit', '-qm', 'T-1 отчёты (squash)')
        else:
            git(self.work, 'merge', '--no-ff', '-q', '-m', f'Merge {BR}', f'origin/{BR}')
        git(self.work, 'push', '-q', 'origin', 'develop')
        git(self.work, 'push', '-q', 'origin', '--delete', BR)

    def facts(self, entry):
        return retro.collect_facts(entry, self.cfg)


class FactsTest(RetroBase):
    def test_merged_as_is(self):
        entry = self.deliver()
        self.merge()
        f = self.facts(entry)
        self.assertEqual(f['outcome'], retro.MERGED)
        self.assertFalse(f.get('human_commits'))

    def test_merged_after_human_changes(self):
        entry = self.deliver()
        self.human_fix_on_branch()
        self.merge()
        f = self.facts(entry)
        self.assertEqual(f['outcome'], retro.MERGED_CHANGED)
        self.assertTrue(any('Человек' in c and 'Проверка на None' in c for c in f['human_commits']))
        self.assertIn('+    if x is None:', f['human_diff'])

    def test_squash(self):
        entry = self.deliver()
        self.human_fix_on_branch()
        self.merge(squash=True)
        f = self.facts(entry)
        self.assertEqual(f['outcome'], retro.SQUASHED)
        self.assertIn('if x is None', f['human_diff'], 'видно, чем итог отличается от работы демона')

    def test_open_and_dropped(self):
        entry = self.deliver()
        f = self.facts(entry)
        self.assertEqual(f['outcome'], retro.OPEN)
        self.assertFalse(retro.has_outcome(f, entry, self.cfg))
        self.assertTrue(retro.has_outcome(f, entry, self.cfg, now=time.time() + 40 * DAY), 'старше max_age — разбираем')
        git(self.work, 'push', '-q', 'origin', '--delete', BR)
        self.assertEqual(self.facts(entry)['outcome'], retro.DROPPED)

    def test_followups_after_merge(self):
        entry = self.deliver()
        self.merge()
        self.commit('feature.py', 'def f(x):\n    return getattr(x, "value", None)\n', 'fix T-1: падение на пустом x')
        git(self.work, 'push', '-q', 'origin', 'develop')
        f = self.facts(entry)
        self.assertTrue(any('падение на пустом x' in c for c in f['followups']))

    def test_human_comments_after_delivery(self):
        entry = self.deliver()
        self.jira.comments += [
            {'body': 'Старый комментарий', 'created': '2000-01-01T00:00:00', 'author': {'displayName': 'Аня'}},
            {'body': 'Забыли про пустой список', 'created': '2999-01-01T00:00:00', 'author': {'displayName': 'Аня'}},
            {'body': f'отчёт демона {retro.ARTEL_REPORT_TAG}', 'created': '2999-01-01T00:00:00'},
        ]
        f = self.facts(entry)
        self.assertEqual([c['body'] for c in f['comments']], ['Забыли про пустой список'])
        self.assertEqual(f['comments'][0]['author'], 'Аня')
        self.assertEqual(f['jira_status'], 'Анализ')

    def test_text_for_agent(self):
        entry = self.deliver()
        self.human_fix_on_branch()
        self.merge()
        text = retro.facts_text(self.facts(entry))
        for part in ('### T-1', 'слита в базу, но перед слиянием люди правили код', 'Коммиты людей', 'if x is None'):
            self.assertIn(part, text)


class ScheduleTest(RetroBase):
    def at(self, hour, minute=0, day=10):
        return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))

    def test_window(self):
        self.assertTrue(retro.in_window(self.cfg, self.at(1, 30)))
        self.assertFalse(retro.in_window(self.cfg, self.at(12)))
        self.cfg['retro'] = {'window': '23:00-02:00'}
        self.assertTrue(retro.in_window(self.cfg, self.at(23, 30)))
        self.assertTrue(retro.in_window(self.cfg, self.at(1)))
        self.assertFalse(retro.in_window(self.cfg, self.at(3)))

    def test_due_once_per_period(self):
        night = self.at(2)
        self.assertTrue(retro.is_due(self.cfg, night))
        retro.save_state(self.cfg, {'last_run': night, 'reviewed': {}})
        self.assertFalse(retro.is_due(self.cfg, self.at(2, day=11)), 'на следующую ночь — рано')
        self.assertTrue(retro.is_due(self.cfg, self.at(2, day=17)), 'через неделю — пора')
        self.cfg['retro'] = {'enabled': False}
        self.assertFalse(retro.is_due(self.cfg, self.at(2, day=17)))

    def test_candidates(self):
        self.deliver('T-1', days_ago=3)
        self.deliver('T-2', days_ago=0)  # слишком свежая
        self.assertEqual([e['issue'] for e in retro.candidates(self.cfg)], ['T-1'])


class ReflectTest(RetroBase):
    def run_retro(self, mode='ok', dry=False):
        with mock.patch.dict(os.environ, {'FAKE_RETRO': mode, 'FAKE_PROMPT_DIR': self.tmp}), \
                contextlib.redirect_stdout(io.StringIO()):
            return retro.run_retro(self.cfg, dry_run=dry)

    def test_full_retro(self):
        self.deliver()
        self.human_fix_on_branch()
        self.merge()
        self.assertEqual(self.run_retro(), 1)
        from jira_gigacode import memory_store
        rows = memory_store.entries(experience.memory_path(self.cfg), self.cfg)
        self.assertTrue(any('проверять входные данные на null' in r['text'] for r in rows))
        self.assertTrue(all(r['source'] == 'ретроспектива' for r in rows))
        self.assertEqual(experience.memory_block(self.cfg), '')
        [report] = os.listdir(os.path.join(self.tmp, 'memory', 'retro'))
        text = read_text(os.path.join(self.tmp, 'memory', 'retro', report))
        self.assertIn('люди добавили проверку на null', text)
        self.assertIn('## Факты', text)
        prompt = read_text(os.path.join(self.tmp, 'retro-0.txt'))
        self.assertIn('Проверка на None', prompt, 'агент видит коммиты людей')
        self.assertIn('LESSONS_START', prompt)
        self.assertEqual(self.run_retro(), 0, 'разобранная задача повторно не разбирается')

    def test_open_task_waits(self):
        self.deliver()
        self.assertEqual(self.run_retro(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'retro-0.txt')), 'агент не запускался')
        self.assertIn('T-1', [e['issue'] for e in retro.candidates(self.cfg)], 'ждёт следующей ретроспективы')

    def test_dry_run_only_shows(self):
        self.deliver()
        self.merge()
        with self.assertLogs(level='INFO') as logs:
            self.assertEqual(self.run_retro(dry=True), 1)
        self.assertIn('Ретроспектива разобрала бы', '\n'.join(logs.output))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'retro-0.txt')))
        self.assertEqual(retro.load_state(self.cfg)['reviewed'], {})

    def test_stopped_retro_is_not_marked(self):
        self.deliver()
        self.merge()
        runtime.running = False
        self.assertEqual(self.run_retro(), 0)
        runtime.running = True
        self.assertEqual(retro.load_state(self.cfg)['reviewed'], {})


class PipelineIntegrationTest(RetroBase):
    def test_successful_task_is_recorded(self):
        with mock.patch.dict(os.environ, {'FAKE_MODE': 'marker'}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.process_issue('T-1', self.cfg, retry_cooldown_sec=60)
        entry = retro.load_deliveries(self.cfg)['T-1']
        git(self.work, 'fetch', '-q', 'origin')
        self.assertEqual(entry['head'], git(self.work, 'rev-parse', f'origin/{BR}'))
        self.assertEqual((entry['branch'], entry['base'], entry['repo']), (BR, 'origin/develop', self.work))

    def test_failed_task_is_not_recorded(self):
        self.jira.can_transition = False
        with mock.patch.dict(os.environ, {'FAKE_MODE': 'marker'}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.process_issue('T-1', self.cfg, retry_cooldown_sec=60)
        self.assertEqual(retro.load_deliveries(self.cfg), {})

    def test_idle_poll_runs_retro_before_explore(self):
        self.jira.issues = []
        calls = []
        with mock.patch.object(pipeline.retro, 'maybe_run', lambda cfg: calls.append('retro')), \
                mock.patch.object(pipeline, 'explore_idle', lambda cfg: calls.append('explore')):
            pipeline.poll_once(self.cfg, retry_cooldown_sec=60)
        self.assertEqual(calls, ['retro', 'explore'])
