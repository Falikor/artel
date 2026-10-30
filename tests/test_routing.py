"""Несколько сервисов под одним КЭ: определение сервиса задачи и работа в его репозитории."""
import contextlib
import io
import os
from unittest import mock

from helpers import DaemonTestCase, git
from jira_gigacode import checks, dry_run, experience, explore, pipeline, routing

SERVICES = [
    {'name': 'back', 'repo_path': '/work/back', 'jenkins': {'job_name': 'hr/deploy-back'}},
    {'name': 'web', 'repo_path': '/work/web', 'keywords': ['web', 'веб', 'фронт'], 'labels': ['web', 'front']},
]


class MatchTest(DaemonTestCase):
    cfg = {'services': SERVICES}

    def route(self, summary, labels=()):
        svc, why = routing.route(summary, list(labels), self.cfg)
        return svc and svc['name'], why

    def test_by_summary_words(self):
        self.assertEqual(self.route('[Бек] Добавить поле в API')[0], 'back')
        self.assertEqual(self.route('Бэк: новый эндпоинт')[0], 'back', 'ё/э и регистр')
        self.assertEqual(self.route('Beck — поправить валидацию')[0], 'back')
        self.assertEqual(self.route('WEB: кнопка «Сохранить»')[0], 'web')
        self.assertEqual(self.route('Веб-форма заявки')[0], 'web')

    def test_by_labels(self):
        self.assertEqual(self.route('Поправить валидацию', ['Backend'])[0], 'back')
        self.assertEqual(self.route('Поправить валидацию', ['front'])[0], 'web')

    def test_whole_words_only(self):
        self.assertIsNone(self.route('Настроить webhook для оплаты')[0], 'webhook — не web')

    def test_nothing_matches(self):
        svc, why = self.route('Поправить валидацию')
        self.assertIsNone(svc)
        self.assertIn('нет признаков', why)

    def test_several_services(self):
        svc, why = self.route('Бек + WEB: новая форма')
        self.assertIsNone(svc)
        self.assertIn('back, web', why)
        self.assertIsNone(self.route('Форма', ['back', 'web'])[0])
        self.assertIsNone(self.route('[Бек] форма', ['web'])[0], 'название и лейбл противоречат — тоже спросить')

    def test_service_config(self):
        cfg = routing.config_for_service({'general': {'repo_path': '/old'}, 'jenkins': {'url': 'u', 'job_name': 'x'}},
                                         SERVICES[0])
        self.assertEqual(cfg['general']['repo_path'], '/work/back')
        self.assertEqual(cfg['jenkins'], {'url': 'u', 'job_name': 'hr/deploy-back'})
        self.assertEqual(cfg['general']['service'], 'back')

    def test_memory_per_service(self):
        base = {'jira': {'project': 'T'}, 'general': {}, 'memory': {}}
        self.assertTrue(experience.memory_path(routing.config_for_service(base, SERVICES[1])).endswith('t-web.md'))

    def test_no_services_means_single_repo(self):
        cfg = {'general': {'repo_path': '/x'}}
        self.assertIs(routing.resolve_issue_service('T-1', cfg), cfg)


class RoutingFlowTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.back = self.make_repo()
        self.web = self.make_repo()
        self.cfg = self.config(self.back)
        self.cfg['services'] = [{'name': 'back', 'repo_path': self.back}, {'name': 'web', 'repo_path': self.web}]

    def poll(self):
        with mock.patch.dict(os.environ, {'FAKE_MODE': 'marker'}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.poll_once(self.cfg, retry_cooldown_sec=60)

    def questions(self):
        return [c for c in self.jira.posted_comments if routing.ROUTING_TAG in c]

    def test_web_task_goes_to_web_repo(self):
        self.jira.summary = 'WEB: кнопка'
        self.poll()
        self.assertIn('feature.py', self.remote_files(self.web, 'feature/ai_team/T-1'))
        self.assertIsNone(self.remote_files(self.back, 'feature/ai_team/T-1'))
        self.assertEqual(self.jira.status, 'Ревью')
        self.assertIn('Сервис — web', self.jira.posted_comments[-1])

    def test_unclear_task_is_asked_once(self):
        self.jira.summary = 'Поправить валидацию'
        self.poll()
        self.poll()
        [question] = self.questions()
        self.assertIn('не понял, к какому сервису', question)
        self.assertIn('{{back}}', question)
        self.assertEqual(self.jira.status, 'Анализ')
        self.assertIsNone(self.remote_files(self.back, 'feature/ai_team/T-1'))

    def test_label_added_after_question(self):
        self.jira.summary = 'Поправить валидацию'
        self.poll()
        self.jira.labels = ['back']
        self.poll()
        self.assertIn('feature.py', self.remote_files(self.back, 'feature/ai_team/T-1'))
        self.assertEqual(len(self.questions()), 1)

    def test_still_unclear_after_change_is_asked_again(self):
        self.jira.summary = 'Поправить валидацию'
        self.poll()
        self.jira.labels = ['back', 'web']
        self.poll()
        questions = self.questions()
        self.assertEqual(len(questions), 2)
        self.assertIn('разбейте задачу', questions[-1])

    def test_dry_run_explains_routing(self):
        self.jira.summary = 'Бек + веб'
        with self.assertLogs(level='INFO') as logs:
            dry_run.dry_run_issue('T-1', self.cfg)
        self.assertIn('Не взял бы задачу', '\n'.join(logs.output))
        self.assertEqual(self.questions(), [], 'dry-run ничего не пишет в задачу')

    def test_explore_uses_service_repo(self):
        self.cfg['explore'] = {'statuses': ['TO DO']}
        self.jira.issues, self.jira.backlog, self.jira.summary = [], ['T-7'], 'WEB: новый экран'
        seen = []
        real = explore.temp_worktree

        def spy(repo, ref, label):
            seen.append(repo)
            return real(repo, ref, label)
        with mock.patch.object(explore, 'temp_worktree', spy), \
                mock.patch.dict(os.environ, {'FAKE_EXPLORE': 'ok'}), contextlib.redirect_stdout(io.StringIO()):
            explore.explore_idle(self.cfg)
        self.assertEqual(seen, [self.web])

    def test_startup_checks_every_service_repo(self):
        git(self.web, 'remote', 'remove', 'origin')
        errors, _ = checks.run_startup_checks(self.cfg)
        self.assertTrue(any(e.startswith('[web] ') and 'origin' in e for e in errors))
        self.assertFalse(any(e.startswith('[back] ') for e in errors))

    def test_repo_path_env_warning(self):
        with mock.patch.dict(os.environ, {'REPO_PATH': '/tmp/x'}):
            _, warnings = checks.run_startup_checks(self.cfg)
        self.assertTrue(any('REPO_PATH' in w for w in warnings))


class ServiceOverridesTest(DaemonTestCase):
    def test_compare_url_per_service(self):
        base = {'general': {'compare_url': 'https://git/common?b={branch}'}}
        own = routing.config_for_service(base, {'name': 'web', 'repo_path': '/w', 'compare_url': 'https://git/web?b={branch}'})
        self.assertEqual(own['general']['compare_url'], 'https://git/web?b={branch}')
        inherited = routing.config_for_service(base, {'name': 'back', 'repo_path': '/b'})
        self.assertEqual(inherited['general']['compare_url'], 'https://git/common?b={branch}')

    def test_done_comment_links_to_service_repo(self):
        back, web = self.make_repo(), self.make_repo()
        cfg = self.config(back, compare_url='https://git/common?b={branch}')
        cfg['services'] = [{'name': 'back', 'repo_path': back},
                           {'name': 'web', 'repo_path': web, 'compare_url': 'https://git/hr-web/compare?from={branch}&to={base}'}]
        self.jira.summary = 'WEB: кнопка'
        with mock.patch.dict(os.environ, {'FAKE_MODE': 'marker'}), contextlib.redirect_stdout(io.StringIO()):
            pipeline.poll_once(cfg, retry_cooldown_sec=60)
        self.assertIn('[посмотреть изменения|https://git/hr-web/compare?from=feature%2Fai_team%2FT-1&to=develop]',
                      self.jira.posted_comments[-1])

    def test_jenkins_inheritance(self):
        cfg = routing.config_for_service({'jenkins': {'url': 'u', 'user': 'robot', 'job_name': 'common'}},
                                         {'name': 'web', 'repo_path': '/w', 'jenkins': {'job_name': 'hr/deploy-web'}})
        self.assertEqual(cfg['jenkins'], {'url': 'u', 'user': 'robot', 'job_name': 'hr/deploy-web'})
        cfg = routing.config_for_service({'jenkins': {'url': 'u', 'job_name': 'common'}}, {'name': 'back', 'repo_path': '/b'})
        self.assertEqual(cfg['jenkins']['job_name'], 'common', 'без своего раздела — общая джоба')


class EnvOverrideWarningsTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.back, self.web = self.make_repo(branches=('develop', 'master')), self.make_repo(branches=('develop', 'master'))
        self.cfg = self.config(self.back)
        self.cfg['services'] = [{'name': 'back', 'repo_path': self.back, 'jenkins': {'job_name': 'b'}},
                                {'name': 'web', 'repo_path': self.web, 'jenkins': {'job_name': 'w'},
                                 'compare_url': 'https://git/w'}]

    def warnings(self, env):
        with mock.patch.dict(os.environ, env):
            return checks.run_startup_checks(self.cfg)[1]

    def test_jenkins_job_env_is_reported(self):
        self.assertFalse(any('перекрывает' in w for w in self.warnings({})))
        for var in ('JENKINS_JOB', 'T_JENKINS_JOB'):
            ws = self.warnings({var: 'одна-на-всех'})
            self.assertTrue(any(var in w and 'jenkins.job_name' in w for w in ws), var)

    def test_compare_url_env_is_reported(self):
        self.assertTrue(any('COMPARE_URL' in w for w in self.warnings({'COMPARE_URL': 'https://x'})))

    def test_unused_overrides_are_not_reported(self):
        # Ни у одного сервиса нет своего branch_prefix — общий BRANCH_PREFIX ничего не перекрывает
        self.assertFalse(any('BRANCH_PREFIX' in w for w in self.warnings({'BRANCH_PREFIX': 'feature/x'})))
