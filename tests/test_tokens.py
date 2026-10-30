"""Подсчёт токенов GigaCode: текст, JSON, записи чатов, отсутствие двойного счёта."""
import json
import os
import time

from helpers import DaemonTestCase
from jira_gigacode import tokens


class UsageFromJsonTest(DaemonTestCase):
    def test_summary_beats_events(self):
        obj = {'executionSummary': {'inputTokens': 100, 'outputTokens': 50, 'totalTokens': 150},
               'events': [{'usage': {'input_tokens': 60, 'output_tokens': 30}},
                          {'usage': {'input_tokens': 40, 'output_tokens': 20}}]}
        usage = tokens._usage_from_json(obj)
        self.assertEqual((usage['input'], usage['output'], usage['total']), (100, 50, 150))

    def test_total_node_beats_per_model(self):
        obj = {'stats': {'total': {'input': 100, 'output': 50, 'total': 150},
                         'models': {'a': {'tokens': {'prompt': 60, 'candidates': 30, 'total': 90}},
                                    'b': {'tokens': {'prompt': 40, 'candidates': 20, 'total': 60}}}}}
        self.assertEqual(tokens._usage_from_json(obj)['total'], 150)

    def test_sibling_models_are_summed(self):
        obj = {'models': {'a': {'tokens': {'prompt': 60, 'candidates': 30}},
                          'b': {'tokens': {'prompt': 40, 'candidates': 20}}}}
        self.assertEqual(tokens._usage_from_json(obj)['total'], 150)

    def test_parent_counters_win_over_children(self):
        obj = {'usage': {'total_tokens': 150, 'details': {'total_tokens': 150}}}
        self.assertEqual(tokens._usage_from_json(obj)['total'], 150)

    def test_string_summary_is_not_a_total(self):
        # Поле summary со строкой (тема задачи) не должно отключать сложение событий
        self.assertIsNone(tokens._usage_from_json({'summary': 'тема', 'note': 'нет токенов'}))

    def test_booleans_are_not_counts(self):
        self.assertIsNone(tokens._usage_from_json({'total': True}))


class ExtractTokenUsageTest(DaemonTestCase):
    def cfg(self, **general):
        return {'general': dict({'gigacode_chats_dir': os.path.join(self.tmp, 'chats')}, **general)}

    def test_text_total(self):
        usage = tokens.extract_token_usage('...\nTotal tokens: 12 345\n', self.cfg(), time.time())
        self.assertEqual((usage['total'], usage['source']), (12345, 'text'))

    def test_text_input_output(self):
        usage = tokens.extract_token_usage('Input tokens: 1,000\nOutput tokens: 250\n', self.cfg(), time.time())
        self.assertEqual((usage['input'], usage['output'], usage['total']), (1000, 250, 1250))

    def test_text_russian(self):
        self.assertEqual(tokens.extract_token_usage('Токенов потрачено: 7 777', self.cfg(), time.time())['total'], 7777)

    def test_custom_regex_last_match(self):
        cfg = self.cfg(tokens_regex=r'spent=(\d+)')
        usage = tokens.extract_token_usage('spent=10\nspent=25\n', cfg, time.time())
        self.assertEqual((usage['total'], usage['source']), (25, 'regex'))

    def test_json_line_in_output(self):
        line = json.dumps({'stats': {'executionSummary': {'inputTokens': 9, 'outputTokens': 1, 'totalTokens': 10}}})
        usage = tokens.extract_token_usage(f'CODE_GENERATION_SUCCESS\n{line}\n', self.cfg(), time.time())
        self.assertEqual((usage['total'], usage['source']), (10, 'json'))

    def test_nothing_found(self):
        self.assertIsNone(tokens.extract_token_usage('просто текст', self.cfg(), time.time()))
        self.assertIsNone(tokens.extract_token_usage(None, self.cfg(), time.time()))

    def _chat(self, name, lines, age=0):
        chats = os.path.join(self.tmp, 'chats', 'projects', 'repo', 'chats')
        os.makedirs(chats, exist_ok=True)
        path = os.path.join(chats, name)
        with open(path, 'w', encoding='utf-8') as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + '\n')
        if age:
            os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_chat_recording_summary_not_doubled(self):
        self._chat('s.jsonl', [{'summary': 'тема задачи', 'usage': {'input_tokens': 60, 'output_tokens': 30}},
                               {'usage': {'input_tokens': 40, 'output_tokens': 20}},
                               {'executionSummary': {'inputTokens': 100, 'outputTokens': 50, 'totalTokens': 150}}])
        usage = tokens.extract_token_usage('', self.cfg(), time.time() - 60)
        self.assertEqual((usage['total'], usage['source']), (150, 'chat-recording'))

    def test_chat_recording_events_summed_without_summary(self):
        self._chat('s.jsonl', [{'usage': {'input_tokens': 60, 'output_tokens': 30}},
                               {'usage': {'input_tokens': 40, 'output_tokens': 20}}])
        self.assertEqual(tokens.extract_token_usage('', self.cfg(), time.time() - 60)['total'], 150)

    def test_old_chats_are_ignored(self):
        self._chat('old.jsonl', [{'usage': {'total_tokens': 999}}], age=3600)
        self.assertIsNone(tokens.extract_token_usage('', self.cfg(), time.time() - 60))

    def test_text_beats_chats(self):
        self._chat('s.jsonl', [{'usage': {'total_tokens': 999}}])
        self.assertEqual(tokens.extract_token_usage('Total tokens: 5', self.cfg(), time.time() - 60)['total'], 5)
