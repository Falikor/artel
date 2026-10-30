"""Browser locale changes only UI labels, never stored names or task content."""
import csv
from html.parser import HTMLParser
from pathlib import Path
import re
import io
import os
from types import SimpleNamespace
from unittest import mock

from helpers import DaemonTestCase
from test_dashboard_data import _load_server


class DashboardLocaleTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()

    def test_static_html_labels_and_accessibility_attributes_have_explicit_translations(self):
        class Labels(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack, self.missing = [], []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                for name in ('aria-label', 'title', 'placeholder', 'content'):
                    if re.search('[А-Яа-яЁё]', attrs.get(name, '')) and not attrs.get('data-i18n-' + name):
                        self.missing.append((tag, name, attrs[name]))
                if tag not in ('meta','link','input','img','br','hr'):
                    self.stack.append((tag, attrs))
            def handle_endtag(self, tag):
                while self.stack:
                    opened, _ = self.stack.pop()
                    if opened == tag:
                        break
            def handle_data(self, text):
                if re.search('[А-Яа-яЁё]', text):
                    _, attrs = self.stack[-1]
                    if not attrs.get('data-i18n-en') and attrs.get('lang') != 'ru':
                        self.missing.append(('text', text.strip()))
        parser = Labels()
        parser.feed(Path(__file__).resolve().parents[1].joinpath('office_dashboard/static/index.html').read_text())
        self.assertEqual(parser.missing, [])

    def test_building_name_provenance_preserves_custom_names_equal_to_defaults(self):
        from artel_dashboard.building import Building
        building = Building(os.path.join(self.tmp, 'building.json'))
        residents = [{'id': 'd%d' % n, 'project': 'P%d' % n} for n in range(17)]
        initial = building.resolve(residents)
        self.assertTrue(all(row['building_title_custom'] is False for row in initial))
        building.rename_building(1, 'Корпус 1')
        building.rename_building(2, 'Команда тестирования')
        seats, rooms = building.load(), building.load_rooms()
        for snapshot in (residents, []):
            rows = Building(building.path).resolve(snapshot)
            self.assertTrue(all(row['building_title_custom'] is True for row in rows))
            self.assertEqual({row['building_title'] for row in rows}, {'Корпус 1', 'Команда тестирования'})
        self.assertEqual(building.load(), seats)
        self.assertEqual(building.load_rooms(), rooms)
        self.assertTrue(all('building_title_custom' not in row for row in rooms.values()))

    def test_csv_language_translates_headers_and_statuses_but_preserves_task_data(self):
        from artel_dashboard.history import history_csv
        rows = [dict(id='tester', issue='TASK-1', result='blocked', service='Сервис', message='Текст задачи без перевода',
                     migration=True, stand='стенд', tokens={'input': 1000000, 'output': 0, 'cached': 0, 'total': 1000000})]
        prices = dict(input=10, output=0, cached=0, currency='₽')
        def read(language=None):
            args = {} if language is None else {'language': language}
            return list(csv.reader(io.StringIO(history_csv(rows, {'tester':'Имя демона'}, {'tester':'123'}, prices, **args).decode('utf-8-sig')), delimiter=';'))
        russian, english = read(), read('en')
        self.assertEqual(russian[0][0], 'Демон')
        self.assertEqual(russian[1][1], 'КЭ 123')
        self.assertEqual(russian[1][4], 'ждёт уточнения')
        self.assertEqual(russian[1][15], '10,00')
        self.assertEqual(english[0][:5], ['Daemon','CI / project','Service','Issue','Outcome'])
        self.assertEqual(english[1][:5], ['Имя демона','CI 123','Сервис','TASK-1','awaiting clarification'])
        self.assertEqual(english[1][15:], ['10.00','стенд','yes','Текст задачи без перевода'])
        self.assertEqual(read('en-US'), english)
        self.assertEqual(read('unknown'), russian)
        self.assertEqual(rows[0]['message'], 'Текст задачи без перевода')

    def test_csv_endpoint_passes_explicit_locale_and_preserves_default(self):
        from artel_dashboard import handler
        view = self.srv.Handler.__new__(self.srv.Handler)
        view.server = SimpleNamespace(logs=self.tmp)
        view.send_csv = mock.Mock()
        view.send_error = mock.Mock()
        with mock.patch.object(handler, 'read_tasks', return_value=[]):
            for query, language in [('', 'ru'), ('?lang=en', 'en'), ('?lang=en-US', 'en-US')]:
                view.path = '/api/history.csv' + query
                view.do_GET()
                view.send_csv.assert_called_with([], language=language)
        view.send_error.assert_not_called()
