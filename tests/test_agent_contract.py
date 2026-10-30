"""Финальный сигнал субагента не должен превращать блокировку в успех."""
import unittest
from unittest import mock

from jira_gigacode import agent_contract as contract, gigacode


class AgentContractTest(unittest.TestCase):
    def result(self, code, output, strict=False):
        with mock.patch.object(gigacode, 'describe_agent_work', return_value='changes'), \
                mock.patch.object(gigacode, 'resolve_param_bool', return_value=strict):
            return gigacode.generation_succeeded('T-1', code, output, '/unused', 'origin/main', 'task/T-1', {})

    def test_success_must_be_final_standalone_line(self):
        self.assertTrue(self.result(0, 'Проверки прошли\nCODE_GENERATION_SUCCESS\n', strict=True))
        for output in ('пример CODE_GENERATION_SUCCESS', '`CODE_GENERATION_SUCCESS`',
                       'CODE_GENERATION_SUCCESS\nНо тесты не прошли'):
            with self.subTest(output=output):
                self.assertFalse(self.result(0, output, strict=True))

    def test_nonzero_exit_overrides_success(self):
        self.assertFalse(self.result(1, 'CODE_GENERATION_SUCCESS'))

    def test_explicit_failure_blocks_legacy_work_fallback(self):
        for status in contract.FAILURE_MARKERS:
            self.assertFalse(self.result(0, 'Изменения есть\n' + status))
            self.assertFalse(self.result(0, status + '\nCODE_GENERATION_SUCCESS'))

    def test_legacy_work_without_marker_still_supported(self):
        self.assertTrue(self.result(0, 'Сделано'))
        self.assertFalse(self.result(0, 'Сделано', strict=True))
