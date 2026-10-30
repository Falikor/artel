import importlib.util
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('artel_updater', Path(__file__).resolve().parents[1] / 'update_artel.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source, self.target = self.base / 'new', self.base / 'installed'
        self.backups = self.base / 'backups'
        for root, value in ((self.source, 'new'), (self.target, 'old')):
            for rel in u.REQUIRED:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('# ' + value if p.suffix == '.py' else value)
        self.active = patch.object(u, 'running', return_value=[])
        self.active.start()
        self.addCleanup(self.active.stop)

    def seal_source(self):
        manifest = {'format': 1, 'sha256': {
            p.as_posix(): u.digest(self.source / p) for p in u.release_files(self.source)}}
        (self.source / u.RELEASE_MANIFEST).write_text(json.dumps(manifest))

    def test_adds_new_dashboard_sections_and_nested_sprites(self):
        payload = {
            'office_dashboard/static/js/stats/memory.js': b'const memory = true;',
            'office_dashboard/artel_dashboard/memory.py': b'enabled = True',
            'office_dashboard/assets/06_CHARACTER_ANIMATIONS/characters/new/atlas.png': b'new sprite',
            'office_dashboard/assets/06_CHARACTER_ANIMATIONS/characters/new/animations.json': b'{"idle": 1}',
            'office_dashboard/assets/LICENSE_EN.txt': b'License',
            'README.md': b'new documentation',
            'CHANGELOG.md': b'release changes',
            'docs/CONFIGURATION.md': b'configuration reference',
            'docs/RUNBOOK.md': b'runbook',
            'config/example.json.sample': b'{"jira": {"project": "EXAMPLE"}}',
            'config/example-services.json.sample': b'{"services": []}',
            'tests/README.md': b'test instructions',
        }
        for rel, data in payload.items():
            path = self.source / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.seal_source()
        backup = u.install(self.source, self.target, self.backups)
        manifest = json.loads((backup / 'manifest.json').read_text())
        for rel, data in payload.items():
            self.assertEqual((self.target / rel).read_bytes(), data)
            self.assertIn(rel, manifest['added'])
        self.assertIn('artel.py', manifest['replaced'])
        self.assertEqual(u.plan(self.source, self.target), [])

    def test_incomplete_or_corrupt_package_fails_before_backup(self):
        sprite = self.source / 'office_dashboard/assets/new/atlas.png'
        sprite.parent.mkdir(parents=True)
        sprite.write_bytes(b'new sprite')
        self.seal_source()
        for damaged in (None, b'corrupt'):
            if damaged is None:
                sprite.unlink()
            else:
                sprite.write_bytes(damaged)
            with self.assertRaises(ValueError):
                u.install(self.source, self.target, self.backups)
            self.assertFalse(self.backups.exists())
            self.assertEqual((self.target / 'artel.py').read_text(), '# old')

    def test_verification_failure_rolls_back_new_files(self):
        new = Path('README.md')
        (self.source / new).write_text('docs')
        real = u.replace_file
        def corrupt(src, dst):
            real(src, dst)
            if dst == self.target / new:
                dst.write_text('incomplete write')
        with patch.object(u, 'replace_file', side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, 'Проверка установленного'):
                u.install(self.source, self.target, self.backups)
        self.assertFalse((self.target / new).exists())
        self.assertEqual((self.target / 'artel.py').read_text(), '# old')

    def test_verify_only_detects_missing_files_without_writing(self):
        argv = ['update_artel.py', '--source', str(self.source), '--target', str(self.target), '--verify-only']
        with patch.object(u.sys, 'argv', argv):
            with self.assertRaisesRegex(ValueError, 'Установка не совпадает'):
                u.main()
        self.assertFalse((self.target / '.artel-update.lock').exists())
        self.assertFalse(self.backups.exists())

    def test_release_archive_contains_payload_and_excludes_runtime_data(self):
        import build_artel_release
        protected = ('config/private.json', 'config/private.json.sample', 'tmp/.env', 'memory/lesson.md',
                     'office_dashboard/building.json', 'office_dashboard/building.json.buildings.json',
                     'logs/history.jsonl', 'logs/t-blocked.json', 'logs/t-notifications.json', 'logs/t-prompts.json', 'tests/test_private.py')
        for rel in protected:
            p = self.source / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('private')
        documentation = ('README.md', 'CHANGELOG.md', 'office_dashboard/README.md',
                         'docs/CONFIGURATION.md', 'docs/RUNBOOK.md', 'config/example.json.sample',
                         'config/example-services.json.sample', 'tests/README.md')
        for rel in documentation:
            p = self.source / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('public example or documentation: ' + rel)
        sprite = self.source / 'office_dashboard/assets/deep/atlas.png'
        sprite.parent.mkdir(parents=True)
        sprite.write_bytes(b'sprite')
        output = self.base / 'release.tar.gz'
        build_artel_release.build(self.source, output)
        with tarfile.open(output) as archive:
            files = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
        manifest = json.loads(files.pop('artel-new/' + u.RELEASE_MANIFEST))
        self.assertEqual(set(files), {'artel-new/' + p for p in manifest['sha256']})
        self.assertEqual(files['artel-new/office_dashboard/assets/deep/atlas.png'], b'sprite')
        for rel in documentation:
            self.assertEqual(files['artel-new/' + rel], (self.source / rel).read_bytes())
        for rel in protected:
            self.assertNotIn('artel-new/' + rel, files)
        self.assertNotIn(b'private', files.values())
        for path, data in files.items():
            self.assertEqual(u.hashlib.sha256(data).hexdigest(), manifest['sha256'][path[len('artel-new/'):]])

    def test_preserves_data_and_backups_originals(self):
        protected = ['config/t.json', 'config/private.json.sample', 'memory/t.md.store.json', 'memory/t.md.rules.md',
                     'logs/t-history.jsonl', 'logs/t-blocked.json', 'logs/t-notifications.json', 'logs/t-prompts.json', 'office_dashboard/names.json',
                     'office_dashboard/building.json', 'office_dashboard/building.json.rooms.json', 'office_dashboard/building.json.buildings.json',
                     'office_dashboard/characters.json', 'office_dashboard/prices.json', '.env']
        for rel in protected:
            for root, text in ((self.target, 'production'), (self.source, 'wrong')):
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
        extra = self.base / 'external-memory'
        extra.mkdir()
        (extra / 'rules.md').write_text('rules')
        backup = u.install(self.source, self.target, self.backups, [extra])
        for rel in protected:
            self.assertEqual((self.target / rel).read_text(), 'production')
            self.assertEqual((backup / 'installation' / rel).read_text(), 'production')
        self.assertEqual((backup / 'external/0/rules.md').read_text(), 'rules')
        self.assertEqual((backup / 'installation/artel.py').read_text(), '# old')
        self.assertEqual((self.target / 'artel.py').read_text(), '# new')
        self.assertIsNone(u.install(self.source, self.target, self.backups))

    def test_syntax_error_prevents_changes(self):
        (self.source / 'artel.py').write_text('def broken(')
        with self.assertRaises(SyntaxError):
            u.install(self.source, self.target, self.backups)
        self.assertFalse(self.backups.exists())
        self.assertEqual((self.target / 'artel.py').read_text(), '# old')

    def test_running_process_prevents_backup_and_update(self):
        with patch.object(u, 'running', return_value=['123']):
            with self.assertRaises(ValueError):
                u.install(self.source, self.target, self.backups)
        self.assertFalse(self.backups.exists())

    def test_symlink_destination_rejected(self):
        original = self.target / 'artel.py'
        original.unlink()
        external = self.base / 'external.py'
        external.write_text('secret = 1')
        original.symlink_to(external)
        with self.assertRaises(ValueError):
            u.plan(self.source, self.target)
        self.assertEqual(external.read_text(), 'secret = 1')

    def test_copy_failure_rolls_back_only_code(self):
        real = u.replace_file
        calls = []
        def failing(src, dst):
            if u.nested(dst, self.target):
                calls.append(dst)
                if len(calls) == 2:
                    raise OSError('disk error')
            real(src, dst)
        with patch.object(u, 'replace_file', side_effect=failing):
            with self.assertRaises(OSError):
                u.install(self.source, self.target, self.backups)
        for rel in u.REQUIRED:
            expected = '# old' if Path(rel).suffix == '.py' else 'old'
            self.assertEqual((self.target / rel).read_text(), expected)
        self.assertIn('rolled_back', next(self.backups.glob('*/manifest.json')).read_text())

    def test_backup_failure_does_not_change_code(self):
        with patch.object(u.shutil, 'copytree', side_effect=OSError('full disk')):
            with self.assertRaises(OSError):
                u.install(self.source, self.target, self.backups)
        self.assertEqual((self.target / 'artel.py').read_text(), '# old')

    def test_partial_source_rejected(self):
        (self.source / 'daemon_state.py').unlink()
        with self.assertRaises(ValueError):
            u.plan(self.source, self.target)

    def test_restart_during_backup_prevents_install(self):
        with patch.object(u, 'running', side_effect=[[], ['123']]):
            with self.assertRaises(ValueError):
                u.install(self.source, self.target, self.backups)
        self.assertEqual((self.target / 'artel.py').read_text(), '# old')
        self.assertTrue(next(self.backups.glob('*/installation/artel.py')).is_file())

    def test_dry_run_does_not_write_lock_or_backup(self):
        argv = ['update_artel.py', '--source', str(self.source), '--target', str(self.target), '--dry-run']
        with patch.object(u.sys, 'argv', argv):
            u.main()
        self.assertFalse((self.target / '.artel-update.lock').exists())
        self.assertEqual((self.target / 'artel.py').read_text(), '# old')
        self.assertFalse((self.base / 'artel-backups').exists())

    def test_backup_inside_target_is_rejected(self):
        argv = ['update_artel.py', '--source', str(self.source), '--target', str(self.target),
                '--backup-dir', str(self.target / 'backups')]
        with patch.object(u.sys, 'argv', argv):
            with self.assertRaises(ValueError):
                u.main()
        self.assertFalse((self.target / 'backups').exists())

    def test_ships_agent_template_without_replacing_installed_agent(self):
        template = Path('subagents/jira-to-deploy-orchestrator.md')
        installed = Path('.gigacode/agents/jira-to-deploy-orchestrator.md')
        for root in (self.source, self.target):
            (root / installed).parent.mkdir(parents=True)
            (root / installed).write_text('local rules' if root == self.target else 'do not install')
        (self.source / template).parent.mkdir()
        (self.source / template).write_text('new template')
        u.install(self.source, self.target, self.backups)
        self.assertEqual((self.target / template).read_text(), 'new template')
        self.assertEqual((self.target / installed).read_text(), 'local rules')
