import io
"""Поиск задач, лейблы Jenkins, временные файлы, кулдаун, комментарии-отчёты."""
import logging
import time
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import git_delivery, git_workspace, issue_report, jenkins, jira_client, logs, reports, retry, runtime

log = logging.getLogger('test')


class SearchTest(DaemonTestCase):
    cfg = {'jira': {'project': 'T'}}

    def test_basic_jql(self):
        self.assertEqual(jira_client.get_issues_by_statuses(['Анализ'], self.cfg), ['T-1'])
        self.assertEqual(self.jira.searches[-1], 'project=T AND status IN ("Анализ") ORDER BY key ASC')

    def test_optional_filters(self):
        cfg = {'jira': {'project': 'T', 'epic_name': 'AI', 'epic_link_field': 'Epic Link',
                        'assignee': 'robot', 'ci_field': '12345'}, 'general': {'ci_id': 'CI0042'}}
        jira_client.get_issues_by_statuses(['Анализ'], cfg)
        jql = self.jira.searches[-1]
        self.assertIn('"Epic Link" = "AI"', jql)
        self.assertIn('assignee = "robot"', jql)
        self.assertIn('cf[12345] = "42"', jql)

    def test_half_epic_config_is_ignored(self):
        jira_client.get_issues_by_statuses(['Анализ'], {'jira': {'project': 'T', 'epic_name': 'AI'}})
        self.assertNotIn('AI', self.jira.searches[-1])

    def test_unknown_status_is_dropped_and_search_retried(self):
        self.jira.invalid_statuses = {'Нет такого'}
        self.assertEqual(jira_client.get_issues_by_statuses(['Нет такого', 'Анализ'], self.cfg), ['T-1'])
        self.assertEqual(self.jira.searches[-1], 'project=T AND status IN ("Анализ") ORDER BY key ASC')
        # Кэш на процесс: в следующий раз сразу без него
        jira_client.get_issues_by_statuses(['Нет такого', 'Анализ'], self.cfg)
        self.assertEqual(len(self.jira.searches), 3)

    def test_all_statuses_unknown(self):
        self.jira.invalid_statuses = {'X'}
        self.assertEqual(jira_client.get_issues_by_statuses(['X'], self.cfg), [])

    def test_jira_down(self):
        self.jira.down = True
        self.assertEqual(jira_client.get_issues_by_statuses(['Анализ'], self.cfg), [])

    def test_unknown_status_messages_parsing(self):
        msgs = ["The value 'A' does not exist for the field 'status'.", 'другое сообщение']
        self.assertEqual(jira_client.extract_unknown_status_values(msgs), ['A'])


class HelpersTest(DaemonTestCase):
    def test_jenkins_labels(self):
        self.assertEqual(jenkins.parse_jenkins_label(['bug', 'Jenkins_IFT', 'jenkins_dev_migration', 'jenkins_', 'jenkins_migration']),
                         [('ift', False), ('dev', True)])

    def test_jenkins_job_path(self):
        self.assertEqual(jenkins.jenkins_job_path('/job/hr/job/deploy back/'), 'hr/job/deploy%20back')

    def test_temp_patterns(self):
        paths = ['.gigacode/tmp/x.py', 'src/tmp_check.py', 'app/main.py', 'scratch_tmp.py', '"tmp1.py"', 'src/']
        self.assertEqual(git_delivery.collect_temp_files(paths, git_delivery.DEFAULT_TEMP_FILE_PATTERNS),
                         ['.gigacode/tmp/x.py', 'src/tmp_check.py', 'scratch_tmp.py', 'tmp1.py'])

    def test_temp_patterns_from_config_replace_defaults(self):
        self.assertEqual(git_delivery.resolve_temp_patterns({'general': {'temp_files': '*.log, debug/*'}}), ('*.log', 'debug/*'))
        self.assertEqual(git_delivery.resolve_temp_patterns({}), git_delivery.DEFAULT_TEMP_FILE_PATTERNS)

    def test_retry_cooldown(self):
        now = 1000.0
        self.assertFalse(retry.note_retry_outcome('T-1', False, 60, now=now))
        self.assertFalse(retry.retry_blocked('T-1', now=now))
        self.assertTrue(retry.note_retry_outcome('T-1', False, 60, now=now))
        self.assertTrue(retry.retry_blocked('T-1', now=now + 59))
        self.assertFalse(retry.retry_blocked('T-1', now=now + 61))
        retry.note_retry_outcome('T-1', True, 60, now=now)
        self.assertFalse(retry.retry_blocked('T-1', now=now))

    def test_mask_secrets(self):
        text = logs.mask_secrets('https://robot:s3cr3t@git.example/r.git ?token=abc&x=1 Authorization: Bearer XYZ')
        for secret in ('s3cr3t', 'abc', 'XYZ'):
            self.assertNotIn(secret, text)

    def test_durations_and_numbers(self):
        self.assertEqual(reports._fmt_duration(20), 'меньше минуты')
        self.assertEqual(reports._fmt_duration(600), '10 мин')
        self.assertEqual(reports._fmt_duration(3900), '1 ч 5 мин')
        self.assertEqual(reports._fmt_int(1234567), '1 234 567')

    def test_compare_link(self):
        cfg = {'general': {'compare_url': 'https://git/x?from={branch}&to={base}&i={issue}'}}
        self.assertEqual(reports.compare_link('T-1', cfg, 'feature/a', 'origin/develop'),
                         'https://git/x?from=feature%2Fa&to=develop&i=T-1')
        self.assertIsNone(reports.compare_link('T-1', {'general': {'compare_url': 'https://git/{nope}'}}, 'b', 'd'))
        self.assertIsNone(reports.compare_link('T-1', {}, 'b', 'd'))


class ResultCommentsTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = {'jira': {'project': 'T', 'status_ready': ['Ревью']},
                    'general': {'name': 'Олег', 'compare_url': 'https://git/c?f={branch}&t={base}'}}

    def test_done_comment(self):
        issue_report.report_start('T-1')
        issue_report.report_set('T-1', branch='feature/ai_team/T-1', base='origin/develop', commits=2,
                     jenkins='started', stand='ift', migration=True, final_status='Ревью',
                     gen_seconds=600, tokens={'total': 123456, 'input': 100000, 'output': 23456})
        reports.post_result_comment('T-1', self.cfg, 'done')
        body = self.jira.posted_comments[-1]
        for part in ('Задача реализована демоном «Олег»', '{{feature/ai_team/T-1}}', 'от {{develop}}',
                     'коммитов: 2', '[посмотреть изменения|https://git/c?f=feature%2Fai_team%2FT-1&t=develop]',
                     'стенд {{ift}} с миграцией — запущен', 'Статус — Ревью', 'генерация 10 мин',
                     '123 456 (вход 100 000, выход 23 456)', issue_report.ARTEL_REPORT_TAG):
            self.assertIn(part, body)

    def test_report_never_looks_like_base_marker(self):
        issue_report.report_start('T-1')
        issue_report.report_set('T-1', branch='feature/ai_team/T-1', base='origin/develop', final_status='Ревью')
        for kind in ('done', 'stuck', 'failed'):
            self.assertIsNone(git_workspace.BASE_BRANCH_MARKER.search(reports.build_result_comment('T-1', self.cfg, kind)), kind)

    def test_jenkins_variants(self):
        for outcome, text in (('no_label', 'нет лейбла'), ('incomplete', 'неполные настройки'),
                              ('failed', 'не запустился')):
            issue_report.report_start('T-1')
            issue_report.report_set('T-1', jenkins=outcome, stand='dev', migration=False)
            self.assertIn(text, reports.build_result_comment('T-1', self.cfg, 'done'))

    def test_failure_comment_once_with_masked_reason(self):
        issue_report.report_start('T-2')
        log.error('[T-2] ❌ Не удалось закоммитить: https://robot:s3cr3t@git/r.git')
        log.error('[T-2] ❌ Пропуск пост-обработки из-за ошибки генерации кода.')
        reports.post_result_comment('T-2', self.cfg, 'failed', until=time.time() + 3600)
        reports.post_result_comment('T-2', self.cfg, 'failed', until=time.time() + 3600)
        self.assertEqual(len(self.jira.posted_comments), 1)
        body = self.jira.posted_comments[0]
        self.assertIn('Не удалось закоммитить', body)
        self.assertNotIn('s3cr3t', body)
        self.assertNotIn('Пропуск пост-обработки', body)

    def test_success_resets_failure_dedup(self):
        reports.post_result_comment('T-3', self.cfg, 'failed')
        reports.post_result_comment('T-3', self.cfg, 'done')
        reports.post_result_comment('T-3', self.cfg, 'failed')
        self.assertEqual(sum('не смог реализовать' in b for b in self.jira.posted_comments), 2)

    def test_reasons_are_per_issue(self):
        issue_report.report_start('T-4')
        log.error('[T-5] чужая ошибка')
        log.error('[T-4] своя ошибка')
        self.assertEqual(logs._issue_errors.reasons('T-4'), ['своя ошибка'])

    def test_wiki_markup_is_neutralized(self):
        self.assertEqual(reports._jira_text('{code}|x'), '(code)/x')

    def test_disabled_and_dry_run(self):
        cfg = {'jira': {'result_comments': False}, 'general': {}}
        reports.post_result_comment('T-1', cfg, 'done')
        runtime.DRY_RUN = True
        reports.post_result_comment('T-1', self.cfg, 'done')
        runtime.DRY_RUN = False
        self.assertEqual(self.jira.posted_comments, [])

    def test_jira_unavailable_does_not_raise(self):
        self.jira.down = True
        reports.post_result_comment('T-1', self.cfg, 'done')


class JenkinsDeployTest(DaemonTestCase):
    """Деплой по лейблу: HTTP к Jenkins подменён, проверяются запросы."""

    def setUp(self):
        super().setUp()
        self.cfg = {'jira': {'project': 'T'},
                    'jenkins': {'url': 'https://jenkins.invalid/', 'user': 'robot', 'token': 'tok', 'job_name': 'hr/job/deploy'}}
        self.requests = []
        issue_report.report_start('T-1')

    def fake_urlopen(self, fail_codes=()):
        test = self

        class Resp:
            status = 201

            def __init__(self, body=b'{}'):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=None, context=None):
            test.requests.append(req)
            if req.full_url.endswith('/crumbIssuer/api/json'):
                return Resp(b'{"crumbRequestField": "Jenkins-Crumb", "crumb": "c1"}')
            code = fail_codes[len(test.requests) - 2] if len(test.requests) - 2 < len(fail_codes) else None
            if code:
                raise jenkins.urllib.error.HTTPError(req.full_url, code, 'err', {}, io.BytesIO(b''))
            return Resp()
        return mock.patch.object(jenkins.urllib.request, 'urlopen', urlopen)

    def test_deploy_with_migration(self):
        self.jira.labels = ['jenkins_ift_migration']
        with self.fake_urlopen():
            jenkins.deploy_for_issue('T-1', 'feature/ai_team/T-1', self.cfg)
        build = self.requests[1]
        self.assertEqual(build.full_url, 'https://jenkins.invalid/job/hr/job/deploy/buildWithParameters')
        body = dict(jenkins.urllib.parse.parse_qsl(build.data.decode()))
        self.assertEqual(body, {'refName': 'feature/ai_team/T-1', 'filter': 'Деплой на IFT', 'MIGRATION': 'true'})
        self.assertEqual(build.get_header('Jenkins-crumb'), 'c1')
        self.assertEqual(issue_report._REPORT['T-1']['jenkins'], 'started')

    def test_falls_back_to_next_endpoint(self):
        self.jira.labels = ['jenkins_dev']
        with self.fake_urlopen(fail_codes=(400,)):
            jenkins.deploy_for_issue('T-1', 'b', self.cfg)
        self.assertTrue(self.requests[2].full_url.endswith('/build'))
        self.assertEqual(issue_report._REPORT['T-1']['jenkins'], 'started')

    def test_all_endpoints_fail(self):
        self.jira.labels = ['jenkins_dev']
        with self.fake_urlopen(fail_codes=(500, 500, 500)):
            jenkins.deploy_for_issue('T-1', 'b', self.cfg)
        self.assertEqual(issue_report._REPORT['T-1']['jenkins'], 'failed')

    def test_no_label_and_incomplete_settings(self):
        with self.fake_urlopen():
            jenkins.deploy_for_issue('T-1', 'b', self.cfg)
        self.assertEqual(issue_report._REPORT['T-1']['jenkins'], 'no_label')
        self.jira.labels = ['jenkins_dev']
        with self.fake_urlopen():
            jenkins.deploy_for_issue('T-1', 'b', {'jira': {'project': 'T'}, 'jenkins': {'url': 'x'}})
        self.assertEqual(issue_report._REPORT['T-1']['jenkins'], 'incomplete')
        self.assertEqual(self.requests, [])
