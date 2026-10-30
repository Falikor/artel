"""Ротация логов и архив logs/archive/ГГГГ-ММ/*.gz: ничего не теряется, файлы не растут бесконечно."""
import contextlib
import glob
import gzip
import io
import os
import time
from unittest import mock

from helpers import DaemonTestCase
from jira_gigacode import gigacode, log_archive, logs, supervisor

DAY = 86400


def gz_text(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return f.read()


class ArchiveTest(DaemonTestCase):
    def setUp(self):
        super().setUp()
        self.logs = os.path.join(self.tmp, 'logs')
        os.makedirs(self.logs, exist_ok=True)
        self.cli_dir = os.path.join(self.tmp, 'cli')
        os.makedirs(self.cli_dir)
        self.cfg = {'logs': {'max_mb': 1, 'cli_keep_days': 14}}

    def write(self, path, text, age_days=0):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        if age_days:
            t = time.time() - age_days * DAY
            os.utime(path, (t, t))
        return path

    def sweep(self, **kw):
        return log_archive.sweep(self.cfg, logs_dir=self.logs, cli_glob=os.path.join(self.cli_dir, 'gigacode_*.log'), **kw)

    def test_big_log_rotates_into_monthly_archive(self):
        path = os.path.join(self.logs, 'ci123-agent.log')
        big = 'строка лога\n' * 120000                    # > 1 МБ
        self.write(path, big)
        [archived] = self.sweep(now=time.mktime((2026, 10, 14, 12, 0, 0, 0, 0, -1)))
        self.assertIn(os.path.join('archive', '2026-10', 'ci123-agent-20261014-120000.log.gz'), archived)
        self.assertEqual(gz_text(archived), big, 'в архиве — всё содержимое')
        self.assertEqual(os.path.getsize(path), 0, 'файл начат заново')
        self.assertEqual(self.sweep(), [], 'маленький лог не трогаем')

    def test_writer_keeps_appending_after_rotation(self):
        """Демон держит файл открытым в режиме дозаписи — после ротации пишет в начало обрезанного файла."""
        path = os.path.join(self.logs, 'ci1-agent.log')
        writer = open(path, 'a', encoding='utf-8')
        self.addCleanup(writer.close)
        writer.write('x' * (1024 * 1024 + 10) + '\n')
        writer.flush()
        self.sweep()
        writer.write('после ротации\n')
        writer.flush()
        with open(path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'после ротации\n')

    def test_rotation_disabled(self):
        self.cfg = {'logs': {'max_mb': 0}}
        self.write(os.path.join(self.logs, 'a-agent.log'), 'x' * (2 * 1024 * 1024))
        self.assertEqual(self.sweep(), [])

    def test_old_gigacode_logs_go_to_archive(self):
        old = self.write(os.path.join(self.cli_dir, 'gigacode_T-1.log'), 'старый прогон', age_days=20)
        fresh = self.write(os.path.join(self.cli_dir, 'gigacode_T-2.log'), 'свежий', age_days=1)
        [archived] = self.sweep()
        month = time.strftime('%Y-%m', time.localtime(time.time() - 20 * DAY))
        self.assertIn(os.path.join('archive', month, 'gigacode', 'gigacode_T-1-'), archived)
        self.assertEqual(gz_text(archived), 'старый прогон')
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_names_never_collide(self):
        a = self.write(os.path.join(self.cli_dir, 'gigacode_T-1.log'), 'первый')
        first = log_archive.archive_file(a, self.logs, when=1000)
        self.write(a, 'второй')
        second = log_archive.archive_file(a, self.logs, when=1000)
        self.assertNotEqual(first, second)
        self.assertEqual((gz_text(first), gz_text(second)), ('первый', 'второй'))

    def test_busy_lock_skips_turn(self):
        if log_archive.fcntl is None:
            self.skipTest('нет fcntl')
        self.write(os.path.join(self.logs, 'a-agent.log'), 'x' * (2 * 1024 * 1024))
        os.makedirs(log_archive.archive_dir(self.logs), exist_ok=True)
        with open(os.path.join(log_archive.archive_dir(self.logs), '.lock'), 'w') as held:
            log_archive.fcntl.flock(held, log_archive.fcntl.LOCK_EX)
            self.assertEqual(self.sweep(), [], 'архиватор занят другим процессом — пропуск')
        self.assertEqual(len(self.sweep()), 1)

    def test_rerun_keeps_previous_gigacode_log(self):
        with mock.patch.object(gigacode, 'cli_log_path', lambda key, purpose='': os.path.join(self.cli_dir, f'gigacode_{key}.log')):
            self.write(os.path.join(self.cli_dir, 'gigacode_T-9.log'), 'первая попытка')
            with contextlib.redirect_stdout(io.StringIO()):
                gigacode.run_cli('T-9', '/bin/echo', 'вторая попытка', self.tmp, 30)
        [archived] = glob.glob(os.path.join(self.logs, 'archive', '*', 'gigacode', 'gigacode_T-9-*.log.gz'))
        self.assertEqual(gz_text(archived), 'первая попытка')

    def test_periodic_runs_once_per_interval(self):
        calls = []
        with mock.patch.object(log_archive, 'sweep', lambda cfg, now=None: calls.append(now) or []):
            tick = log_archive.Periodic(3600)
            tick(now=10_000)
            tick(now=12_000)
            tick(now=14_000)
        self.assertEqual(calls, [10_000, 14_000])

    def test_summary(self):
        self.write(os.path.join(self.logs, 'a-agent.log'), 'x' * (2 * 1024 * 1024))
        self.sweep(now=time.mktime((2026, 9, 1, 3, 0, 0, 0, 0, -1)))
        [(month, count, size)] = log_archive.summary(self.logs)
        self.assertEqual((month, count), ('2026-09', 1))
        self.assertGreater(size, 0)


class SupervisedLoggingTest(DaemonTestCase):
    def handlers_after_setup(self, env):
        import logging
        root = logging.getLogger()
        saved = list(root.handlers)

        def restore():
            for h in list(root.handlers):
                root.removeHandler(h)
                if h not in saved:
                    h.close()
            for h in saved:
                root.addHandler(h)
        self.addCleanup(restore)
        with mock.patch.dict(os.environ, env), mock.patch.object(logs, 'LOGS_DIR', os.path.join(self.tmp, 'logs')):
            logs.setup_logging({'jira': {'project': 'T'}}, mode='check')
        return [type(h).__name__ for h in logging.getLogger().handlers]

    def test_no_duplicate_stdout_log_under_supervisor(self):
        self.assertIn('StreamHandler', self.handlers_after_setup({}))
        self.assertNotIn('StreamHandler', self.handlers_after_setup({logs.SUPERVISED_ENV: '1'}))

    def test_supervisor_marks_children(self):
        self.assertEqual(logs.SUPERVISED_ENV, supervisor.SUPERVISED_ENV)
