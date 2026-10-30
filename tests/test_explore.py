"""Полезный простой: исследование задач из бэклога и комментарий с предложениями."""
import contextlib
import io
import os
import time
from unittest import mock

from helpers import DaemonTestCase, git, read_text
from jira_gigacode import explore, pipeline, reports, requirements_snapshot


class ExploreBase(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.work = self.make_repo()
        self.cfg = self.config(self.work)
        self.cfg['explore'] = {'statuses': ['TO DO', 'Backlog']}
        self.jira.issues = []          # задач на реализацию нет — демон в простое
        self.jira.backlog = ['T-7']
        self.prompts = os.path.join(self.tmp, 'prompts')
        os.makedirs(self.prompts)

    def idle(self, mode='ok', cfg=None):
        env = {'FAKE_EXPLORE': mode, 'FAKE_MODE': 'fail', 'FAKE_PROMPT_DIR': self.prompts}
        with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            return explore.explore_idle(cfg or self.cfg)

    def explore_comments(self):
        return [c for c in self.jira.posted_comments if reports.EXPLORE_TAG in c]


class ExploreTest(ExploreBase):

    def test_proposals_are_posted_as_comment(self):
        self.assertEqual(self.idle(), 1)
        [comment] = self.explore_comments()
        self.assertIn('изучил задачу', comment)
        self.assertIn('h4. Вопросы', comment, 'Markdown переведён в разметку Jira')
        self.assertIn('*пустым*', comment)
        self.assertIn('{{api/\\{id\\}}}', comment)
        self.assertNotIn('думаю...', comment, 'в комментарий идёт только итог между маркерами')
        prompt = read_text(os.path.join(self.prompts, 'explore-0.txt'))
        self.assertTrue(prompt.startswith('/opsx:explore T-7: Сделать отчёт'))
        self.assertIn('Ничего не меняй', prompt)

    def test_each_task_once(self):
        self.idle()
        self.assertEqual(self.idle(), 0)
        with mock.patch.object(explore.time, 'time', return_value=time.time() + 30 * 24 * 3600):
            self.assertEqual(self.idle(), 0, 'задачу не меняли — повторно не изучаем даже через месяц')
        self.assertEqual(len(self.explore_comments()), 1)

    def test_changed_task_is_reexplored_after_pause(self):
        self.idle()
        self.jira.updated = 'изменили описание'
        self.jira.description = 'Новая постановка отчёта'
        self.assertEqual(self.idle(), 0, 'меньше двух недель — ждём')
        with mock.patch.object(explore.time, 'time', return_value=time.time() + 15 * 24 * 3600):
            self.assertEqual(self.idle(), 1)
        self.assertEqual(len(self.explore_comments()), 1)
        self.assertEqual(len(self.jira.updated_comments), 1)
        self.assertEqual(self.jira.updated_comments[0]['id'], '1')
        self.assertEqual(self.idle(), 0)

    def test_two_week_boundary_and_persisted_record(self):
        snapshot = requirements_snapshot.fetch_snapshot('T-7', self.cfg)
        explore._remember(self.cfg, 'T-7', 'old', snapshot)
        recorded_at = explore.load_explored(self.cfg)['T-7']['at']
        meta = dict(snapshot['fields'], updated='new', description='Новая постановка')
        boundary = recorded_at + 14 * 24 * 3600
        self.assertFalse(explore.should_explore('T-7', meta, self.cfg, now=boundary - 1)[0])
        self.assertTrue(explore.should_explore('T-7', meta, self.cfg, now=boundary)[0])

    def test_old_config_and_env_cannot_shorten_two_week_interval(self):
        explore._remember(self.cfg, 'T-7', 'old')
        recorded_at = explore.load_explored(self.cfg)['T-7']['at']
        self.cfg['explore']['min_hours_between'] = 24
        for env in ({}, {'EXPLORE_MIN_HOURS': '1'}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                self.assertFalse(explore.should_explore(
                    'T-7', {'updated': 'new'}, self.cfg, now=recorded_at + 25 * 3600)[0])

    def test_longer_configured_interval_is_respected(self):
        explore._remember(self.cfg, 'T-7', 'old')
        recorded_at = explore.load_explored(self.cfg)['T-7']['at']
        self.cfg['explore']['min_hours_between'] = 30 * 24
        self.assertFalse(explore.should_explore(
            'T-7', {'updated': 'new'}, self.cfg, now=recorded_at + 15 * 24 * 3600)[0])

    def test_existing_comment_is_respected(self):
        self.jira.comments.append({'id': '1', 'body': reports.build_explore_comment(self.cfg, 'Старые предложения'),
                                   'author': self.jira.myself, 'created': '2026'})
        self.assertEqual(self.idle(), 0)
        self.assertEqual(self.explore_comments(), [])
        self.assertIn('T-7', explore.load_explored(self.cfg))

    def later(self):
        return mock.patch.object(explore.time, 'time', return_value=time.time() + 15 * 24 * 3600)

    def human_reply(self, text='Ответ аналитика: выгрузка нужна в CSV'):
        comment = {'id': 'human-1', 'author': {'key': 'analyst'}, 'body': text, 'issue': 'T-7'}
        self.jira.comments.append(comment)
        return comment

    def test_external_reply_revisits_same_comment_and_is_in_prompt(self):
        self.idle()
        self.human_reply()
        self.assertEqual(self.idle(), 0, 'ответ не отменяет минимальные 14 дней между предложениями')
        with self.later():
            self.assertEqual(self.idle(), 1)
            self.assertEqual(self.idle(), 0)
        self.assertEqual(len(self.explore_comments()), 1)
        self.assertEqual([c['id'] for c in self.jira.updated_comments], ['1'])
        self.assertIn('выгрузка нужна в CSV', read_text(os.path.join(self.prompts, 'explore-1.txt')))

    def test_status_only_and_own_reports_do_not_revisit(self):
        self.idle()
        self.jira.updated = 'смена статуса'
        self.jira.status = 'Backlog'
        self.jira.comments.append({'id': 'notice', 'author': self.jira.myself,
                                   'body': reports.ARTEL_REPORT_TAG + '\nНужно решение владельца'})
        with self.later():
            self.assertEqual(self.idle(), 0)
        self.assertEqual(self.jira.updated_comments, [])

    def test_human_quoting_artel_report_is_not_ignored(self):
        self.idle()
        self.human_reply(reports.ARTEL_REPORT_TAG + '\nНа ваш вопрос: нет, нужен JSON')
        with self.later():
            self.assertEqual(self.idle(), 1)

    def test_edited_and_removed_external_comment_are_changes(self):
        reply = self.human_reply('Исходное уточнение')
        self.idle()
        reply['body'] = 'Исправленное уточнение'
        with self.later():
            self.assertEqual(self.idle(), 1)
        self.jira.comments.remove(reply)
        with mock.patch.object(explore.time, 'time', return_value=time.time() + 30 * 24 * 3600):
            self.assertEqual(self.idle(), 1)

    def test_comment_read_failure_does_not_replace_baseline(self):
        self.idle()
        before = explore.load_explored(self.cfg)['T-7']
        self.human_reply()
        with self.later(), mock.patch.object(explore.jira_client, 'fetch_comments', return_value=None):
            self.assertEqual(self.idle(), 0)
        self.assertEqual(explore.load_explored(self.cfg)['T-7'], before)
        with self.later():
            self.assertEqual(self.idle(), 1)

    def test_changes_during_research_are_not_swallowed_by_publication(self):
        real_run = explore.run_cli

        def run_and_edit(*args, **kwargs):
            result = real_run(*args, **kwargs)
            self.jira.description = 'Аналитик изменил постановку, пока работал агент'
            return result

        with mock.patch.object(explore, 'run_cli', side_effect=run_and_edit):
            self.idle()
        with self.later():
            self.assertEqual(self.idle(), 1)
        self.assertIn('Аналитик изменил', read_text(os.path.join(self.prompts, 'explore-1.txt')))

    def test_legacy_state_baselines_without_resending_then_tracks_changes(self):
        explore._remember(self.cfg, 'T-7', 'old')
        with self.later():
            self.assertEqual(self.idle(), 0)
            self.assertIn('fingerprint', explore.load_explored(self.cfg)['T-7'])
            self.human_reply()
            self.assertEqual(self.idle(), 1)

    def test_missing_state_recovers_own_comment_and_tracks_future_changes(self):
        self.idle()
        os.unlink(explore._state_path(self.cfg))
        with self.later():
            self.assertEqual(self.idle(), 0)
            self.human_reply()
            self.assertEqual(self.idle(), 1)
        self.assertEqual(len(self.explore_comments()), 1)

    def test_another_author_comment_cannot_claim_our_exploration(self):
        self.human_reply(reports.build_explore_comment(self.cfg, 'Цитата чужого комментария'))
        self.assertEqual(self.idle(), 1)

    def test_disabled_reexploration_does_not_revisit_external_reply(self):
        self.idle()
        self.human_reply()
        self.cfg['explore']['reexplore_on_update'] = False
        with self.later():
            self.assertEqual(self.idle(), 0)

    def test_blocked_task_does_not_spawn_another_idle_research(self):
        from pathlib import Path
        from jira_gigacode import blocked, retry_control
        path = Path(self.tmp) / 'blocked.json'
        self.jira.backlog = ['T-7', 'T-8']
        for status in ('waiting', 'resuming'):
            with self.subTest(status=status):
                with retry_control.transaction(path) as data:
                    data['T-7'] = {'status': status}
                with mock.patch.object(blocked, 'path_for', return_value=path), \
                        mock.patch.object(explore, 'explore_issue') as run:
                    self.assertEqual(self.idle(), 1)
                self.assertEqual(run.call_args.args[0], 'T-8')

    def test_one_task_per_cycle(self):
        self.jira.backlog = ['T-7', 'T-8', 'T-9']
        self.assertEqual(self.idle(), 1)
        self.cfg['explore']['max_per_cycle'] = 5
        self.assertEqual(self.idle(), 2)

    def test_disabled_without_statuses(self):
        cfg = self.config(self.work)
        self.assertEqual(self.idle(cfg=cfg), 0)
        cfg['explore'] = {'statuses': ['TO DO'], 'enabled': False}
        self.assertEqual(self.idle(cfg=cfg), 0)

    def test_fallback_without_markers(self):
        self.idle(mode='nomarkers')
        self.assertIn('разбить задачу на две части', self.explore_comments()[0])

    def test_empty_result_is_not_posted_and_not_retried(self):
        self.idle(mode='empty')
        self.assertEqual(self.explore_comments(), [])
        self.assertEqual(self.idle(mode='ok'), 0)

    def test_repository_is_untouched(self):
        head = git(self.work, 'rev-parse', 'HEAD')
        self.idle(mode='vandal')
        self.assertFalse(os.path.exists(os.path.join(self.work, 'explorer_was_here.txt')))
        self.assertEqual(git(self.work, 'status', '--porcelain'), '')
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD'), head)
        self.assertEqual(len(git(self.work, 'worktree', 'list').splitlines()), 1)

    def test_custom_template_for_subagent(self):
        self.cfg['explore']['prompt_template'] = 'вызови суб агента /my-explorer FAKE_EXPLORE_PROMPT {key} {summary} {description}'
        self.jira.description = 'JSON вида {"a": 1}'
        self.idle()
        prompt = read_text(os.path.join(self.prompts, 'explore-0.txt'))
        self.assertIn('/my-explorer FAKE_EXPLORE_PROMPT T-7 Сделать отчёт JSON вида {"a": 1}', prompt)

    def test_exploration_does_not_teach_by_default(self):
        from jira_gigacode import experience
        experience.append_lessons(self.cfg, 'T-1', ['Тесты: make test'], 'генерация')
        from jira_gigacode import memory_store
        path = experience.memory_path(self.cfg)
        row = memory_store.entries(path, self.cfg)[0]
        memory_store.approve(path, self.cfg, row['id'], 'Проверено владельцем')
        self.idle()
        prompt = read_text(os.path.join(self.prompts, 'explore-0.txt'))
        self.assertIn('Тесты: make test', prompt, 'опыт исследование читает')
        self.assertNotIn('LESSONS_START', prompt, 'но уроков не просит')
        self.assertNotIn('make build', experience.memory_block(self.cfg), 'и не пишет')

    def test_lessons_from_exploration_when_enabled(self):
        from jira_gigacode import experience
        self.cfg['explore']['learn'] = True
        self.idle()
        from jira_gigacode import memory_store
        rows = memory_store.entries(experience.memory_path(self.cfg), self.cfg)
        self.assertTrue(any('make build' in r['text'] for r in rows))
        self.assertEqual(experience.memory_block(self.cfg), '')

    def test_poll_once_explores_only_when_idle(self):
        with mock.patch.object(pipeline, 'explore_idle') as idle:
            pipeline.poll_once(self.cfg, retry_cooldown_sec=60)
        idle.assert_called_once()
        self.jira.issues = ['T-1']
        with mock.patch.object(pipeline, 'explore_idle') as idle, \
                mock.patch.object(pipeline, 'process_issue'):
            pipeline.poll_once(self.cfg, retry_cooldown_sec=60)
        idle.assert_not_called()


class MarkdownToJiraTest(DaemonTestCase):
    def test_conversion(self):
        text = '## Заголовок\n**жирный** и `код`\n- пункт\n  - вложенный\n1. первый\n```\nx = {1: 2}\n```'
        out = reports.md_to_jira(text)
        for part in ('h4. Заголовок', '*жирный*', '{{код}}', '* пункт', '** вложенный', '# первый',
                     '{code}\nx = {1: 2}\n{code}'):
            self.assertIn(part, out)

    def test_braces_and_secrets(self):
        out = reports.md_to_jira('{panel} https://u:secret@host/x')
        self.assertIn('\\{panel\\}', out)
        self.assertNotIn('secret', out)

    def test_unclosed_code_block(self):
        self.assertTrue(reports.md_to_jira('```\nкод').endswith('{code}'))


class BacklogSearchTest(DaemonTestCase):
    """JQL бэклога — проект, КЭ и статусы, без эпика и исполнителя; выдача листается страницами."""

    def setUp(self):
        super().setUp()
        self.cfg = self.config(os.path.join(self.tmp, 'repo'))
        self.cfg['jira'].update({'epic_name': 'AI', 'epic_link_field': 'Epic Link', 'assignee': 'robot',
                                 'ci_field': '12345'})
        self.cfg['general']['ci_id'] = 'CI0042'
        self.cfg['explore'] = {'statuses': ['TO DO', 'Backlog']}

    def test_jql_always_limits_project_even_with_ci(self):
        self.jira.backlog = ['T-1']
        list(explore.iter_backlog(self.cfg))
        self.assertEqual(self.jira.searches[-1],
                         'project=T AND cf[12345] = "42" AND status IN ("TO DO", "Backlog") ORDER BY updated DESC')

    def test_without_ci_falls_back_to_project(self):
        del self.cfg['general']['ci_id']
        self.jira.backlog = ['T-1']
        list(explore.iter_backlog(self.cfg))
        self.assertEqual(self.jira.searches[-1], 'project=T AND status IN ("TO DO", "Backlog") ORDER BY updated DESC')

    def test_task_search_keeps_epic_and_assignee(self):
        from jira_gigacode import jira_client
        jira_client.get_issues_by_statuses(['Анализ'], self.cfg)
        jql = self.jira.searches[-1]
        for part in ('project=T', '"Epic Link" = "AI"', 'cf[12345] = "42"', 'assignee = "robot"'):
            self.assertIn(part, jql)

    def test_pages_through_explored_tasks(self):
        self.jira.backlog = [f'T-{i}' for i in range(120)]
        for key in self.jira.backlog[:75]:  # первые 75 уже изучены и с тех пор не менялись
            explore._remember(self.cfg, key, self.jira.updated)
        with mock.patch.object(explore, 'explore_issue') as run:
            self.assertEqual(explore.explore_idle(self.cfg), 1)
        self.assertEqual(run.call_args.args[0], 'T-75', 'первая неизученная — за пределами первой страницы')
        self.assertEqual(self.jira.search_pages, [(0, 50), (50, 50)])

    def test_scan_limit(self):
        self.cfg['explore']['max_scan'] = 30
        self.jira.backlog = [f'T-{i}' for i in range(120)]
        keys = [k for k, _ in explore.iter_backlog(self.cfg)]
        self.assertEqual(len(keys), 30)
        self.assertEqual(self.jira.search_pages, [(0, 30)])

    def test_fields_come_from_search(self):
        self.jira.backlog = ['T-5']
        self.jira.fields_by_issue['T-5'] = {'summary': 'Своя тема', 'description': 'Текст',
                                            'updated': 'u1', 'status': {'name': 'TO DO'}}
        [(key, meta)] = list(explore.iter_backlog(self.cfg))
        self.assertEqual((key, meta['summary'], meta['updated'], meta['status']), ('T-5', 'Своя тема', 'u1', 'TO DO'))

    def test_startup_check_warns_without_ci(self):
        from jira_gigacode import checks
        work = self.make_repo(branches=('develop', 'master'))
        cfg = self.config(work)
        cfg['explore'] = {'statuses': ['TO DO']}
        _, warnings = checks.run_startup_checks(cfg)
        self.assertTrue(any('по всему проекту' in w for w in warnings))
        cfg['jira']['ci_field'], cfg['general']['ci_id'] = '12345', 'CI42'
        _, warnings = checks.run_startup_checks(cfg)
        self.assertFalse(any('по всему проекту' in w for w in warnings))


class ExploreCommentUpdateTest(ExploreBase):
    def post(self, text='Новые предложения по задаче'):
        return reports.post_explore_comment('T-7', self.cfg, text)

    def existing(self, body=None, author=None, cid='7'):
        c = {'id': cid, 'issue': 'T-7', 'created': '2026-10-01',
             'author': author if author is not None else dict(self.jira.myself),
             'body': body if body is not None else reports.build_explore_comment(self.cfg, 'Старый текст')}
        self.jira.comments.append(c)
        return c

    def test_updates_same_id_and_replaces_body_after_restart(self):
        old = self.existing()
        self.assertEqual(self.post(), '7')
        self.assertEqual(self.jira.posted_comments, [])
        self.assertIn('Новые предложения', old['body'])
        self.assertNotIn('Старый текст', old['body'])
        self.assertEqual(self.post('Ещё один результат'), '7')
        self.assertEqual(len(self.jira.comments), 1)

    def test_migrates_old_comment_format(self):
        legacy = reports.build_explore_comment(self.cfg, 'Старый текст').split('\n{color:#97a0af}ARTEL_EXPLORE_OWNER=')[0]
        old = self.existing(body=legacy)
        self.assertEqual(self.post(), '7')
        self.assertIn('ARTEL_EXPLORE_OWNER=', old['body'])
        self.assertEqual(self.jira.posted_comments, [])

    def test_other_author_and_other_daemon_are_not_edited(self):
        for body, author in [
            (reports.build_explore_comment(self.cfg, 'Чужой текст'), {'key': 'human', 'displayName': 'Робот'}),
            (reports.build_explore_comment(self.cfg, 'Другой демон').replace('ARTEL_EXPLORE_OWNER=t', 'ARTEL_EXPLORE_OWNER=other'), self.jira.myself),
            ('Обычный комментарий робота', self.jira.myself),
        ]:
            with self.subTest(body=body):
                self.jira.comments.clear()
                old = self.existing(body=body, author=author)
                self.assertTrue(self.post())
                self.assertEqual(old['body'], body)
        self.assertEqual(self.jira.updated_comments, [])

    def test_updates_latest_duplicate_only(self):
        first = self.existing(cid='7')
        last = self.existing(cid='8')
        self.assertEqual(self.post(), '8')
        self.assertIn('Старый текст', first['body'])
        self.assertIn('Новые предложения', last['body'])
        self.assertEqual(len(self.jira.comments), 2)

    def test_failed_edit_never_creates_duplicate(self):
        self.existing()
        with mock.patch.object(reports.jira_client, 'update_comment', return_value=None):
            self.assertFalse(self.post())
        self.assertEqual(self.jira.posted_comments, [])

    def test_failed_read_or_unknown_identity_does_not_post(self):
        with mock.patch.object(reports.jira_client, 'fetch_comments', return_value=None):
            self.assertFalse(self.post())
        self.jira.myself = {'displayName': 'Робот'}
        self.assertFalse(self.post())
        self.assertEqual(self.jira.posted_comments, [])

    def test_put_api_contract(self):
        with mock.patch.object(reports.jira_client, 'jira_request', return_value={'id': '7'}) as request:
            reports.jira_client.update_comment('T-7', '7', 'Текст', self.cfg)
        request.assert_called_once_with('PUT', '/rest/api/2/issue/T-7/comment/7',
                                        data={'body': 'Текст'}, config=self.cfg)

    def test_stable_owner_survives_daemon_rename(self):
        self.existing()
        self.cfg['general']['name'] = 'Новое имя'
        self.assertEqual(self.post(), '7')
        self.assertEqual(self.jira.posted_comments, [])

    def test_dry_run_never_reads_or_writes_jira(self):
        with mock.patch.object(reports.runtime, 'DRY_RUN', True), \
                mock.patch.object(reports.jira_client, 'jira_request') as request:
            self.assertFalse(self.post())
        request.assert_not_called()
