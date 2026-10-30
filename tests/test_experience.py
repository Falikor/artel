"""Опыт между задачами: уроки агента, файл опыта, заметки по задаче."""
import os

from helpers import DaemonTestCase, read_text
from jira_gigacode import experience, memory_store


class LessonsParsingTest(DaemonTestCase):
    def test_extract(self):
        out = 'работа\nLESSONS_START\n- Тесты: make test\n* Миграции в db/\n2) Линтер: ruff\n\nLESSONS_END\n'
        self.assertEqual(experience.extract_lessons(out), ['Тесты: make test', 'Миграции в db/', 'Линтер: ruff'])

    def test_last_block_wins_and_limits(self):
        many = '\n'.join(f'- урок {i}' for i in range(10))
        out = f'LESSONS_START\n- старый\nLESSONS_END\nLESSONS_START\n{many}\n- ' + 'x' * 500 + '\nLESSONS_END'
        lessons = experience.extract_lessons(out)
        self.assertEqual(len(lessons), experience.MAX_LESSONS)
        self.assertEqual(lessons[0], 'урок 0')

    def test_long_lesson_is_cut(self):
        out = 'LESSONS_START\n- ' + 'я' * 1000 + '\nLESSONS_END'
        self.assertLessEqual(len(experience.extract_lessons(out)[0]), experience.MAX_LESSON_CHARS + 1)

    def test_no_block(self):
        self.assertEqual(experience.extract_lessons('нет уроков'), [])
        self.assertEqual(experience.extract_lessons('LESSONS_END ... LESSONS_START'), [])


class MemoryFileTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = self.config(os.path.join(self.tmp, 'repo'))

    def test_path_uses_instance_key(self):
        self.assertTrue(experience.memory_path(self.cfg).endswith(os.path.join('memory', 't.md')))
        cfg = dict(self.cfg, general=dict(self.cfg['general'], ci_id='CI42'))
        self.assertTrue(experience.memory_path(cfg).endswith('ci42.md'))

    def test_append_creates_file_and_dedups(self):
        self.assertEqual(experience.append_lessons(self.cfg, 'T-1', ['Тесты: make test', 'Сборка: make'], 'генерация'), 2)
        self.assertEqual(experience.append_lessons(self.cfg, 'T-2', ['Тесты: make test', 'Новый урок'], 'ревью'), 1)
        rows = memory_store.entries(experience.memory_path(self.cfg), self.cfg)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['status'] == 'candidate' for r in rows))

    def test_block_for_prompt(self):
        self.assertEqual(experience.memory_block(self.cfg), '')
        experience.append_lessons(self.cfg, 'T-1', ['Тесты: make test'], 'генерация')
        self.assertEqual(experience.memory_block(self.cfg), '')
        path = experience.memory_path(self.cfg)
        row = memory_store.entries(path, self.cfg)[0]
        memory_store.approve(path, self.cfg, row['id'], 'Владелец выполнил make test')
        block = experience.memory_block(self.cfg)
        self.assertIn('Тесты: make test', block)
        self.assertIn('справка, а не приказ', block)

    def test_legacy_is_preserved_but_not_automatically_trusted(self):
        path = experience.memory_path(self.cfg)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = '# Опыт\n## 2026-01-01 · T-1 · генерация\n- Тесты: make test\n'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        self.assertEqual(experience.memory_block(self.cfg), '')
        self.assertEqual(read_text(path), text)
        self.assertEqual(len(memory_store.entries(path, self.cfg)), 1)
        self.assertEqual(len(memory_store.entries(path, self.cfg)), 1)

    def test_disabled(self):
        experience.append_lessons(self.cfg, 'T-1', ['урок'], 'генерация')
        self.cfg['memory']['enabled'] = False
        self.assertEqual(experience.memory_block(self.cfg), '')
        self.assertEqual(experience.lessons_request(self.cfg), '')

    def test_manual_only_mode(self):
        self.cfg['memory']['auto_append'] = False
        self.assertEqual(experience.append_lessons(self.cfg, 'T-1', ['урок'], 'генерация'), 0)
        self.assertEqual(experience.lessons_request(self.cfg), '')
        self.assertFalse(os.path.exists(experience.memory_path(self.cfg)))


class GenerationUsesMemoryTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)
        self.prompt_file = os.path.join(self.tmp, 'prompt.txt')

    def generate(self, key, mode):
        os.environ['FAKE_PROMPT_FILE'] = self.prompt_file
        try:
            return self.run_generation(key, self.cfg, mode)
        finally:
            del os.environ['FAKE_PROMPT_FILE']

    def test_lessons_are_saved_and_offered_next_time(self):
        ok, _ = self.generate('T-1', 'marker_lessons')
        self.assertTrue(ok)
        self.assertIn('LESSONS_START', read_text(self.prompt_file), 'агента просят вывести уроки')
        rows = memory_store.entries(experience.memory_path(self.cfg), self.cfg)
        self.assertTrue(any('db/migrations' in r['text'] for r in rows))
        self.generate('T-2', 'marker')
        self.assertNotIn('Миграции лежат в db/migrations', read_text(self.prompt_file))

    def test_failed_generation_does_not_teach(self):
        self.generate('T-1', 'fail')
        self.assertFalse(os.path.exists(experience.memory_path(self.cfg)))


class IssueNotesTest(DaemonTestCase):
    def test_roundtrip(self):
        cfg = self.config(self.tmp)
        self.assertEqual(experience.previous_review_block(cfg, 'T-1'), '')
        experience.save_review_notes(cfg, 'T-1', '- поправь тесты')
        self.assertIn('поправь тесты', experience.previous_review_block(cfg, 'T-1'))
        self.assertEqual(experience.review_notes(cfg, 'T-2'), '')
        experience.clear_issue_notes(cfg, 'T-1')
        self.assertEqual(experience.review_notes(cfg, 'T-1'), '')


class ForgetSourceTest(DaemonTestCase):
    TEXT = ('# Опыт демона «Олег»\n\nЭтот файл…\n'
            '\n## 2026-10-10 · T-1 · генерация\n- Тесты: make test\n'
            '\n## 2026-10-11 · T-7 · исследование\n- Задача T-7 про отчёты, нужен новый эндпоинт\n- Ещё догадка\n'
            '\n## 2026-10-12 · T-2 · ревью\n- Линтер: ruff\n'
            '\n## 2026-10-13 · T-8 · исследование\n- Догадка по T-8\n')

    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp, 'mem.md')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(self.TEXT)

    def test_removes_only_exploration_sections(self):
        self.assertEqual(experience.forget_source(self.path, 'исследование'), 2)
        text = read_text(self.path)
        for kept in ('# Опыт демона', 'make test', 'Линтер: ruff', '· генерация', '· ревью'):
            self.assertIn(kept, text)
        for gone in ('T-7', 'Догадка по T-8', '· исследование'):
            self.assertNotIn(gone, text)
        self.assertEqual(read_text(self.path + '.bak'), self.TEXT, 'копия до уборки')

    def test_dry_run_changes_nothing(self):
        self.assertEqual(experience.forget_source(self.path, 'исследование', dry_run=True), 2)
        self.assertEqual(read_text(self.path), self.TEXT)
        self.assertFalse(os.path.exists(self.path + '.bak'))

    def test_nothing_to_remove(self):
        self.assertEqual(experience.forget_source(self.path, 'доработка'), 0)
        self.assertFalse(os.path.exists(self.path + '.bak'))
        self.assertEqual(experience.forget_source(os.path.join(self.tmp, 'нет.md'), 'исследование'), 0)

    def test_artel_command(self):
        import contextlib
        import io
        from unittest import mock
        from jira_gigacode import supervisor
        out = io.StringIO()
        with mock.patch.object(supervisor, 'memory_files', return_value=[self.path]), contextlib.redirect_stdout(out):
            self.assertEqual(supervisor.main(['memory', 'forget-explore', '--dry-run']), 0)
            self.assertIn('найдено записей:   2', out.getvalue())
            self.assertEqual(read_text(self.path), self.TEXT)
            self.assertEqual(supervisor.main(['memory', 'forget-explore']), 0)
        self.assertNotIn('исследование', read_text(self.path))
        with mock.patch('sys.stderr'):
            self.assertEqual(supervisor.main(['memory']), 2)
