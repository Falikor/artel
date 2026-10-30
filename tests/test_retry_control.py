import json
import tempfile
import unittest
from pathlib import Path
from jira_gigacode import retry_control as rc

class RetryControlTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'a-retries.json'

    def test_interrupted_requires_explicit_permission(self):
        self.assertIsNone(rc.begin(self.path,'T-1','config'))
        self.assertIn('прервана', rc.begin(self.path,'T-1','config'))
        rc.decide(self.path,'T-1','resume')
        self.assertIsNone(rc.begin(self.path,'T-1','config'))

    def test_cooldown_is_persistent(self):
        rc.begin(self.path,'T-1','config')
        rc.outcome(self.path,'T-1',False,60,now=100)
        rc.begin(self.path,'T-1','config',now=101)
        self.assertTrue(rc.outcome(self.path,'T-1',False,60,now=102))
        self.assertEqual(rc.begin(Path(str(self.path)),'T-1','config',now=103),'Кулдаун после ошибок')
        self.assertIsNone(rc.begin(self.path,'T-1','config',now=163))

    def test_operator_block_survives_outcome_and_isolated_instances(self):
        rc.begin(self.path,'T-1','config')
        rc.decide(self.path,'T-1','block')
        rc.outcome(self.path,'T-1',False,60)
        self.assertIn('Исключена',rc.begin(self.path,'T-1','config'))
        self.assertIsNone(rc.begin(self.path.parent/'b-retries.json','T-1','config'))

    def test_corrupt_file_fails_closed(self):
        self.path.write_text('broken')
        with self.assertRaises(ValueError): rc.begin(self.path,'T-1','config')
        self.assertEqual(self.path.read_text(),'broken')

    def test_pause_and_validation(self):
        rc.decide(self.path,'T-1','pause',60)
        self.assertEqual(rc.begin(self.path,'T-1','config'),'Пауза владельца')
        with self.assertRaises(ValueError): rc.decide(self.path,'../bad','resume')
        with self.assertRaises(ValueError): rc.decide(self.path,'T-1','pause',-5)

    def test_pause_revokes_previous_approval(self):
        rc.begin(self.path,'T-1','old')
        rc.decide(self.path,'T-1','resume')
        rc.decide(self.path,'T-1','pause',1)
        self.assertIn('Изменился', rc.begin(self.path,'T-1','new',now=10**12))
