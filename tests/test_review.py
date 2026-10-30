"""Независимое ревью перед деплоем и переводом, доработка по замечаниям."""
import contextlib
import io
import os
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import experience, pipeline, retry, review

BR = 'feature/ai_team/T-1'


class ParseReviewTest(DaemonTestCase):
    def test_approve(self):
        r = review.parse_review('...\nREVIEW_VERDICT: APPROVE\nREVIEW_NOTES_START\nОк\nREVIEW_NOTES_END')
        self.assertEqual((r['verdict'], r['notes']), ('approve', 'Ок'))

    def test_last_verdict_wins(self):
        r = review.parse_review('REVIEW_VERDICT: APPROVE\nпередумал\nREVIEW_VERDICT: REQUEST_CHANGES\n'
                                'REVIEW_NOTES_START\n- поправь\nREVIEW_NOTES_END')
        self.assertEqual((r['verdict'], r['notes']), ('changes', '- поправь'))

    def test_no_verdict(self):
        self.assertEqual(review.parse_review('не понял задачу')['verdict'], 'none')

    def test_changes_without_notes_keeps_tail(self):
        r = review.parse_review('много текста\nREVIEW_VERDICT: REQUEST_CHANGES')
        self.assertIn('много текста', r['notes'])

    def test_instruction_text_is_not_a_verdict(self):
        # Формат в команде ревьюеру записан так, что сам по себе не совпадает с вердиктом
        prompt = review.build_review_prompt('T-1', {'jira': {}, 'general': {}, 'memory': {'enabled': False}},
                                            BR, 'origin/develop', 'diff')
        self.assertEqual(review.parse_review(prompt)['verdict'], 'none')

    def test_blocking_rules(self):
        cfg = {'review': {}}
        self.assertTrue(review.blocks_delivery({'verdict': 'changes'}, cfg))
        self.assertFalse(review.blocks_delivery({'verdict': 'approve'}, cfg))
        self.assertFalse(review.blocks_delivery({'verdict': 'none'}, cfg))
        self.assertTrue(review.blocks_delivery({'verdict': 'none'}, {'review': {'on_no_verdict': 'block'}}))
        self.assertFalse(review.blocks_delivery({'verdict': 'changes'}, {'review': {'block_on_changes': False}}))
        self.assertFalse(review.blocks_delivery(None, cfg))


class ReviewFlowTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.prompts = os.path.join(self.tmp, 'prompts')
        os.makedirs(self.prompts)

    def cfg(self, **review_opts):
        cfg = self.config(self.work)
        cfg['review'] = dict({'enabled': True}, **review_opts)
        return cfg

    def run_task(self, cfg, mode='marker', review_mode='approve', rework='fix'):
        env = {'FAKE_MODE': mode, 'FAKE_REVIEW': review_mode, 'FAKE_REWORK': rework, 'FAKE_PROMPT_DIR': self.prompts}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            pipeline.process_issue('T-1', cfg, retry_cooldown_sec=3600)

    def prompt(self, name):
        with open(os.path.join(self.prompts, name), encoding='utf-8') as f:
            return f.read()

    def test_approved_work_is_transitioned(self):
        self.run_task(self.cfg())
        self.assertEqual(self.jira.status, 'Ревью')
        done = self.jira.posted_comments[-1]
        self.assertIn('Ревью — одобрено независимым ревьюером', done)
        review_prompt = self.prompt('review-0.txt')
        self.assertIn('feature.py', review_prompt, 'ревьюер получает diff')
        self.assertIn('Сделать отчёт', review_prompt, 'и текст задачи')

    def test_changes_then_rework_then_approve(self):
        self.run_task(self.cfg(), review_mode='changes,approve')
        self.assertEqual(self.jira.status, 'Ревью')
        files = self.remote_files(self.work, BR)
        self.assertIn('test_fix.py', files, 'доработка доставлена в remote')
        self.assertIn('Добавь тест на пустой список', self.prompt('rework-0.txt'))
        self.assertIn('после доработки', self.jira.posted_comments[-1])

    def test_unresolved_changes_block_delivery(self):
        cfg = self.cfg(max_rework_rounds=0)
        self.run_task(cfg, review_mode='changes')
        self.assertEqual(self.jira.status, 'Анализ', 'задача не переведена')
        self.assertEqual(self.jira.transitions_done, [])
        comment = self.jira.posted_comments[-1]
        self.assertIn('не прошла независимое ревью', comment)
        self.assertIn('Добавь тест на пустой список', comment)
        self.assertFalse(retry.pending_transition_active('T-1'))
        self.assertIn('Добавь тест', experience.review_notes(cfg, 'T-1'))
        # Следующая попытка получает замечания в команде, а после успеха они удаляются
        self.run_task(cfg, review_mode='approve')
        self.assertIn('Добавь тест на пустой список', self.prompt('generate-1.txt'))
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertEqual(experience.review_notes(cfg, 'T-1'), '')

    def test_reviewer_lessons_go_to_memory(self):
        cfg = self.cfg(max_rework_rounds=0)
        self.run_task(cfg, review_mode='changes')
        from jira_gigacode import memory_store
        rows = memory_store.entries(experience.memory_path(cfg), cfg)
        self.assertTrue(any('make test' in row['text'] for row in rows))
        self.assertEqual(experience.memory_block(cfg), '')

    def test_rework_without_changes_stops(self):
        self.run_task(self.cfg(max_rework_rounds=2), review_mode='changes', rework='nothing')
        self.assertEqual(self.jira.status, 'Анализ')
        self.assertFalse(os.path.exists(os.path.join(self.prompts, 'rework-1.txt')), 'вторая доработка не нужна')

    def test_no_verdict_passes_by_default(self):
        self.run_task(self.cfg(), review_mode='none')
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertIn('ревьюер не дал вердикта', self.jira.posted_comments[-1])

    def test_no_verdict_can_block(self):
        self.run_task(self.cfg(on_no_verdict='block'), review_mode='none')
        self.assertEqual(self.jira.status, 'Анализ')

    def test_reviewer_cannot_touch_working_clone_or_remote(self):
        self.run_task(self.cfg(), review_mode='vandal')
        self.assertNotIn('reviewer_was_here.py', self.remote_files(self.work, BR))
        self.assertFalse(os.path.exists(os.path.join(self.work, 'reviewer_was_here.py')))
        worktrees = git(self.work, 'worktree', 'list').splitlines()
        self.assertEqual(len(worktrees), 1, 'временная копия удалена')

    def test_disabled_review_is_skipped(self):
        cfg = self.cfg()
        cfg['review']['enabled'] = False
        self.run_task(cfg, review_mode='changes')
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertFalse(any(name.startswith('review-') for name in os.listdir(self.prompts)))

    def test_review_tokens_are_added(self):
        cfg = self.cfg()
        with mock.patch.object(review, 'extract_token_usage', return_value={'total': 100, 'source': 'text'}):
            self.run_task(cfg)
        self.assertIn('Токены GigaCode', self.jira.posted_comments[-1])

    def test_rework_blocked_is_not_delivered_despite_changes(self):
        original = review.run_cli
        def blocked(*args, **kwargs):
            code, output = original(*args, **kwargs)
            if kwargs.get('purpose') == 'rework':
                output += '\nCODE_GENERATION_BLOCKED\n'
            return code, output
        with mock.patch.object(review, 'run_cli', side_effect=blocked):
            self.run_task(self.cfg(), review_mode='changes,approve')
        self.assertEqual(self.jira.status, 'Анализ')
        self.assertNotIn('test_fix.py', self.remote_files(self.work, BR))

    def test_rework_strict_mode_requires_final_marker(self):
        original = review.run_cli
        def no_marker(*args, **kwargs):
            code, output = original(*args, **kwargs)
            if kwargs.get('purpose') == 'rework':
                output = output.replace('CODE_GENERATION_SUCCESS', 'Готово')
            return code, output
        cfg = self.cfg()
        cfg['general']['require_success_marker'] = True
        with mock.patch.object(review, 'run_cli', side_effect=no_marker):
            self.run_task(cfg, review_mode='changes,approve')
        self.assertEqual(self.jira.status, 'Анализ')
        self.assertNotIn('test_fix.py', self.remote_files(self.work, BR))
