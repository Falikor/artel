"""Memory lifecycle: trust boundaries, budgets, migration and explicit curation."""
import json
import os
import time
from unittest import mock
from helpers import DaemonTestCase, read_text
from jira_gigacode import experience, memory_store as store


class MemoryLifecycleTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(self.tmp)
        self.path = experience.memory_path(self.cfg)

    def add(self, text, issue='T-1'):
        store.observe(self.path, self.cfg, issue, 'генерация', [text])
        return next(e for e in store.entries(self.path, self.cfg) if e['text'] == text)['id']

    def approve(self, text, scope=()):
        key = self.add(text)
        store.approve(self.path, self.cfg, key, 'Проверено владельцем: команда и код', scope)
        return key

    def test_no_self_promotion_and_confirmation_requires_evidence(self):
        key = self.add('Запуск тестов: make test')
        for _ in range(3):
            self.add('Запуск тестов: make test', 'T-2')
        self.assertEqual(experience.memory_block(self.cfg), '')
        with self.assertRaises(ValueError):
            store.approve(self.path, self.cfg, key, ' ')
        self.assertEqual(store.entries(self.path, self.cfg)[0]['status'], 'candidate')

    def test_scope_and_pinned_rules_survive_budget(self):
        self.cfg['memory']['max_chars'] = 80
        self.approve('Проверка миграций: make migration-test', ['db/migrations'])
        _, rules, _ = store.paths(self.path)
        with open(rules, 'w') as f:
            f.write('Не менять публичный API.')
        self.assertNotIn('migration-test', store.active_text(self.path, self.cfg, 'frontend'))
        text = store.active_text(self.path, self.cfg, 'изменения db/migrations')
        self.assertIn('migration-test', text)
        self.assertTrue(text.startswith('Не менять'))
        self.assertLessEqual(len(text), 80)
        with open(rules, 'w') as f:
            f.write('x' * 81)
        with self.assertRaises(ValueError):
            store.active_text(self.path, self.cfg)

    def test_capacity_archive_and_history_rotation(self):
        self.cfg['memory'].update(max_candidates=2, history_max_bytes=400)
        for i in range(60):
            self.add('Конкретный факт ' + str(i))
        self.assertEqual(len(store.entries(self.path, self.cfg)), 2)
        audit = store.paths(self.path)[2]
        self.assertTrue(os.path.exists(audit + '.1'))
        self.assertFalse(os.path.exists(audit + '.2'))
        self.assertLessEqual(os.path.getsize(audit), 16384)
        self.assertLessEqual(os.path.getsize(audit + '.1'), 16384)

    def test_expiry_requires_reconfirmation_and_repetition_does_not_renew(self):
        key = self.approve('Команда тестирования: pytest tests/')
        now = time.time()
        with mock.patch.object(store.time, 'time', return_value=now + 91 * 86400):
            self.assertEqual(experience.memory_block(self.cfg), '')
            row = store.entries(self.path, self.cfg)[0]
            self.assertTrue(row['needs_review'])
            self.assertEqual(row['status'], 'candidate')
            store.approve(self.path, self.cfg, key, 'Повторно проверил команду')
            self.assertIn('pytest', experience.memory_block(self.cfg))

    def test_replace_preserves_audit_and_reject_blocks_reobservation(self):
        old = self.approve('Сборка выполняется командой make')
        new = self.add('Сборка выполняется командой make build')
        store.approve(self.path, self.cfg, new, 'Проверен новый Makefile', replaces=old)
        self.assertNotIn(old, [r['id'] for r in store.entries(self.path, self.cfg)])
        self.assertIn('superseded', read_text(store.paths(self.path)[2]))
        store.reject(self.path, self.cfg, new)
        self.add('Сборка выполняется командой make build')
        self.assertEqual(experience.memory_block(self.cfg), '')

    def test_corrupt_store_is_not_overwritten(self):
        self.add('Запуск: make test')
        path = store.paths(self.path)[0]
        with open(path, 'w') as f:
            f.write('{ broken')
        self.assertEqual(experience.append_lessons(self.cfg, 'T-2', ['другое'], 'ревью'), 0)
        self.assertEqual(read_text(path), '{ broken')

    def test_forget_exploration_also_cleans_new_store(self):
        store.observe(self.path, self.cfg, 'T-1', 'исследование', ['Непроверенное предположение'])
        self.assertEqual(experience.forget_source(self.path, 'исследование', dry_run=True), 1)
        self.assertEqual(len(store.entries(self.path, self.cfg)), 1)
        self.assertEqual(experience.forget_source(self.path, 'исследование'), 1)
        self.assertEqual(store.entries(self.path, self.cfg), [])

    def test_cli_approve_list_and_config_limits(self):
        import contextlib
        import io
        key = self.add('Запуск тестов: pytest')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(store.command(['approve', self.path, key, '--evidence', 'Проверил тесты']), 0)
            self.assertEqual(store.command(['list', self.path]), 0)
        self.assertIn('[confirmed]', output.getvalue())

    def test_similarity_is_only_a_suggestion(self):
        self.add('Использовать make test для проверки изменений')
        self.add('Не использовать make test для проверки изменений')
        rows = store.entries(self.path, self.cfg)
        self.assertEqual(len(rows), 2)
        self.assertEqual(store.similar(rows, rows[0]), [rows[1]['id']])
        self.assertEqual(experience.memory_block(self.cfg), '')

    def test_operators_and_command_case_are_not_deduplicated(self):
        self.add('Условие: a != b')
        self.add('Условие: a == b')
        self.add('Команда: make Test')
        self.add('Команда: make test')
        self.assertEqual(len(store.entries(self.path, self.cfg)), 4)

    def test_relevance_selects_matching_entry_with_small_budget(self):
        self.approve('Сборка фронтенда: npm build')
        self.approve('База данных: make db-test')
        self.cfg['memory']['max_chars'] = 35
        text = store.active_text(self.path, self.cfg, 'Сборка фронтенда')
        self.assertIn('npm build', text)
        self.assertNotIn('db-test', text)

    def test_parallel_observations_are_not_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda i: store.observe(self.path, self.cfg, 'T-' + str(i),
                                                    'генерация', ['Команда ' + str(i)]), range(12)))
        self.assertEqual(len(store.entries(self.path, self.cfg)), 12)
