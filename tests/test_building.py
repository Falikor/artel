"""Forty residents, stable seats across absence/restart, group boundaries and looks."""
import json
import os
from helpers import DaemonTestCase
from test_dashboard_data import _load_server


class BuildingTest(DaemonTestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _load_server()
        from artel_dashboard.building import Building
        cls.Building = Building

    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp, 'building.json')
        self.building = self.Building(self.path)
        self.characters = self.srv.Characters(os.path.join(self.tmp, 'characters.json'))

    def residents(self, count=40):
        ds = [{'id': f'd{i:02}', 'project': 'TEST'} for i in range(count)]
        self.characters.resolve(ds)
        return ds

    def test_manual_building_before_previous_is_full_and_restart(self):
        ds = self.residents(40)
        original = self.building.resolve(ds)
        rid = self.building.create_room('Testing', 'new')
        rooms = self.Building(self.path).resolve(ds)
        self.assertEqual(next(r for r in rooms if r['id'] == rid)['building_level'], 17)
        self.assertEqual({r['id']: r['building_level'] for r in original},
                         {r['id']: r['building_level'] for r in rooms if r['id'] != rid})
        self.building.move(ds[0]['id'], room=rid)
        self.building.resolve(ds)
        self.assertEqual(ds[0]['office_id'], rid)
        self.building.rename_building(2, 'Testing building')
        self.assertEqual(self.Building(self.path).load_building_names()['2'], 'Testing building')

    def test_explicit_building_capacity_and_duplicate_names(self):
        first = self.building.create_room('Testing')
        second = self.building.create_room('Testing', 1)
        self.assertNotEqual(first, second)
        for i in range(14):
            self.building.create_room('Testing', 1)
        with self.assertRaises(ValueError):
            self.building.create_room('Overflow', 1)
        for value in (True, 0, -1, '1', 2):
            with self.assertRaises(ValueError):
                self.building.create_room('Bad', value)
        rid = self.building.create_room('Next', 'new')
        self.assertEqual(self.building.load_rooms()[rid]['building_level'], 17)
        self.building.edit_room(first, 'delete')
        refill = self.building.create_room('Refill', 1)
        self.assertEqual(self.building.load_rooms()[refill]['building_level'], 1)

    def test_move_entire_office_preserves_offline_seats_and_empty_building(self):
        ds = self.residents(10)
        room = self.building.resolve(ds)[0]['id']
        before = self.building.load()
        self.building.move_room(room, 'new')
        self.assertEqual(self.building.load(), before)
        restarted = self.Building(self.path)
        rooms = restarted.resolve(ds[:3])
        moved = next(r for r in rooms if r['id'] == room)
        self.assertEqual(moved['building_level'], 17)
        self.assertEqual(moved['occupied'], 10)
        self.assertEqual([b['offices'] for b in restarted.list_buildings()], [0, 1])
        with self.assertRaises(ValueError):
            restarted.delete_building(2)
        restarted.rename_building(1, 'Empty')
        restarted.delete_building(1)
        self.assertEqual([b['number'] for b in restarted.list_buildings()], [2])
        self.assertNotIn('1', restarted.load_building_names())
        restarted.move_room(room, 'new')
        self.assertEqual(restarted.load_rooms()[room]['building_level'], 33)
        self.assertEqual(restarted.load(), before)

    def test_move_office_rejects_full_or_invalid_destination_without_changes(self):
        room = self.building.create_room('Source')
        self.building.create_room('Target', 'new')
        for i in range(15):
            self.building.create_room(str(i), 2)
        before = self.building.load_rooms()
        for target in (2, True, 0, '2', 99):
            with self.assertRaises(ValueError):
                self.building.move_room(room, target)
            self.assertEqual(before, self.building.load_rooms())
        self.building.move_room(room, 1)
        self.assertEqual(before, self.building.load_rooms())

    def test_last_empty_building_deleted_does_not_reappear_or_reuse_name(self):
        room = self.building.create_room('Temporary')
        self.building.edit_room(room, 'delete')
        self.assertEqual(self.building.list_buildings()[0]['offices'], 0)
        self.building.delete_building(1)
        self.assertEqual(self.building.list_buildings(), [])
        rooms = self.building.resolve(self.residents(1))
        self.assertEqual(rooms[0]['building_level'], 17)

    def test_forty_have_four_rooms_unique_seats_and_looks(self):
        ds = self.residents()
        rooms = self.building.resolve(ds)
        self.assertEqual(len(rooms), 4)
        self.assertTrue(all(len(r['daemons']) == 10 for r in rooms))
        self.assertEqual(len({(d['office_id'], d['office_slot']) for d in ds}), 40)
        self.assertEqual(len({(d['character'], d['appearance']) for d in ds}), 40)

    def test_absent_resident_keeps_seat_and_newcomer_does_not_steal_it(self):
        ds = self.residents(10)
        self.building.resolve(ds)
        original = {d['id']: (d['office_id'], d['office_slot'], d['appearance']) for d in ds}
        remaining = ds[1:] + [{'id': 'new', 'project': 'TEST', 'character': 'manager_navy'}]
        self.Building(self.path).resolve(remaining)
        self.assertNotEqual(remaining[-1]['office_id'], ds[0]['office_id'])
        self.Building(self.path).resolve(list(reversed(ds)))
        self.assertEqual(original, {d['id']: (d['office_id'], d['office_slot'], d['appearance']) for d in ds})

    def test_project_service_and_explicit_office_group(self):
        ds = [{'id':'a','project':'A','service':'backend'}, {'id':'b','project':'A','service':'frontend'},
              {'id':'c','project':'B'}, {'id':'d','project':'A','office_group':'payments'}]
        rooms = self.building.resolve(ds)
        self.assertEqual(len(rooms), 4)
        old = ds[0]['office_id']
        ds[0]['detail'] = {'service':'frontend'}
        self.building.resolve(ds)
        self.assertEqual(ds[0]['office_id'], old)

    def test_selected_variant_survives_restart(self):
        ds = self.residents(1)
        self.building.resolve(ds)
        self.building.set_variant(ds[0]['id'], 4)
        self.Building(self.path).resolve(ds)
        self.assertEqual(ds[0]['appearance'], 4)
        for bad in (-1, 6, '2', True):
            with self.assertRaises(ValueError):
                self.building.set_variant(ds[0]['id'], bad)

    def test_corrupt_layout_is_not_silently_reset(self):
        with open(self.path, 'w') as f:
            f.write('broken')
        with self.assertRaises(ValueError):
            self.building.resolve(self.residents(1))

    def test_state_response_contains_building_and_preserves_offline_seat(self):
        import time
        from types import SimpleNamespace
        from unittest import mock
        ds = self.residents(40)
        handler = self.srv.Handler.__new__(self.srv.Handler)
        handler.server = SimpleNamespace(logs=self.tmp, names=None, characters=self.characters, building=self.building)
        with mock.patch('artel_dashboard.handler.read_all', return_value={'now':time.time(), 'daemons':ds}):
            snap = handler.state()
        self.assertEqual(len(snap['offices']), 4)
        self.assertTrue(all('appearance' in d and 'office_slot' in d for d in snap['daemons']))

    def test_explicit_group_overrides_service(self):
        ds = [{'id':'one', 'project':'P', 'office_group':'Payments', 'service':'backend'},
              {'id':'two', 'project':'P', 'office_group':'Payments', 'service':'frontend'}]
        self.assertEqual(len(self.building.resolve(ds)), 1)

    def test_manual_move_restart_capacity_and_return_to_auto(self):
        ds = self.residents(11)
        self.building.resolve(ds)
        first = ds[0]['office_id']
        with self.assertRaisesRegex(ValueError, 'нет свободных'):
            self.building.move(ds[10]['id'], first)
        self.building.move(ds[0]['id'], name='Команда поиска')
        self.Building(self.path).resolve(ds)
        custom = ds[0]['office_id']
        self.assertNotEqual(first, custom)
        self.assertTrue(ds[0]['office_manual'])
        self.building.move(ds[10]['id'], first)
        self.building.resolve(ds)
        self.assertEqual(ds[10]['office_slot'], 0)
        self.assertEqual(ds[10]['office_id'], first)
        self.building.move(ds[0]['id'], 'auto')
        self.building.resolve(ds)
        self.assertFalse(ds[0]['office_manual'])
        self.assertNotEqual(ds[0]['office_id'], custom)

    def test_invalid_move_does_not_change_assignments(self):
        ds = self.residents(1)
        self.building.resolve(ds)
        old = self.building.load()
        for room, name in [('missing', None), (None, ''), (None, 'x' * 61)]:
            with self.assertRaises(ValueError):
                self.building.move(ds[0]['id'], room, name)
            self.assertEqual(self.building.load(), old)

    def test_report_filter_uses_persisted_members_and_demon(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        ds = self.residents(11)
        self.building.resolve(ds)
        handler = self.srv.Handler.__new__(self.srv.Handler)
        handler.server = SimpleNamespace(building=self.building)
        rows = [{'id':d['id']} for d in ds]
        with patch.object(handler, 'state', return_value={}):
            room = ds[0]['office_id']
            self.assertEqual(len(handler.filter_office(rows, {'office':[room]})), 10)
            self.assertEqual(handler.filter_office(rows, {'office':[room], 'id':[ds[10]['id']]}), [])
            self.assertEqual(handler.filter_office(rows, {'office':['missing']}), [])

    def test_room_rename_empty_delete_and_restart(self):
        ds = self.residents(1)
        self.building.resolve(ds)
        old = ds[0]['office_id']
        slot = ds[0]['office_slot']
        self.building.edit_room(old, 'rename', 'Инфраструктура')
        rooms = self.Building(self.path).resolve(ds)
        self.assertEqual(ds[0]['office_title'], 'Инфраструктура')
        self.assertEqual(ds[0]['office_slot'], slot)
        with self.assertRaises(ValueError):
            self.building.edit_room(old, 'delete')
        # A missing daemon is still a resident, not an empty room.
        self.building.resolve([])
        with self.assertRaises(ValueError):
            self.building.edit_room(old, 'delete')
        self.building.move(ds[0]['id'], name='Новый')
        rooms = self.building.resolve(ds)
        empty = next(r for r in rooms if r['id'] == old)
        self.assertEqual(empty['occupied'], 0)
        self.assertEqual(empty['daemons'], [])
        # Empty rooms remain valid move destinations.
        self.building.move(ds[0]['id'], old)
        self.building.resolve(ds)
        self.assertEqual(ds[0]['office_id'], old)
        self.building.move(ds[0]['id'], name='Новый')
        self.building.resolve(ds)
        self.building.edit_room(old, 'delete')
        self.assertNotIn(old, {r['id'] for r in self.Building(self.path).resolve(ds)})

    def test_room_names_validate_without_mutation(self):
        ds = self.residents(1)
        self.building.resolve(ds)
        old = self.building.load_rooms()
        for name in ('', '   ', 'x' * 61, None):
            with self.assertRaises(ValueError):
                self.building.edit_room(ds[0]['office_id'], 'rename', name)
        self.assertEqual(self.building.load_rooms(), old)

    def test_building_levels_survive_rename_restart_absence_and_new_room(self):
        ds = self.residents(21)
        initial = {r['id']: r['building_level'] for r in self.building.resolve(ds)}
        self.assertEqual(set(initial.values()), {1, 2, 3})
        seats = {d['id']: (d['office_id'], d['office_slot']) for d in ds}
        self.building.edit_room(ds[0]['office_id'], 'rename', 'Ядро')
        restarted = self.Building(self.path)
        self.assertEqual(initial, {r['id']: r['building_level'] for r in restarted.resolve([])})
        later = list(reversed(ds)) + [{'id': 'new-team', 'project': 'NEW'}]
        updated = {r['id']: r['building_level'] for r in restarted.resolve(later)}
        self.assertTrue(all(updated[rid] == level for rid, level in initial.items()))
        self.assertEqual(set(updated.values()), {1, 2, 3, 4})
        self.assertEqual(seats, {d['id']: (d['office_id'], d['office_slot']) for d in ds})

    def test_legacy_catalog_gets_levels_without_changing_seats(self):
        ds = self.residents(11)
        self.building.resolve(ds)
        seats = self.building.load()
        catalog = self.building.load_rooms()
        for room in catalog.values():
            room.pop('building_level', None)
        with open(self.building.rooms_path, 'w') as f:
            json.dump(catalog, f)
        rows = self.Building(self.path).resolve(ds)
        self.assertEqual({r['building_level'] for r in rows}, {1, 2})
        self.assertEqual(seats, self.building.load())

    def test_building_titles_default_at_sixteen_office_boundary(self):
        ds = [{'id': f'd{i:02}', 'project': f'Project {i}'} for i in range(33)]
        rooms = self.building.resolve(ds)
        self.assertEqual(self.building.load_building_names(), {})
        self.assertFalse(os.path.exists(self.building.buildings_path))
        self.assertEqual({r['building_level']: r['building_title'] for r in rooms},
                         {level: f'Корпус {(level - 1) // 16 + 1}' for level in range(1, 34)})

    def test_building_name_persists_without_changing_rooms_seats_or_addresses(self):
        ds = [{'id': f'd{i:02}', 'project': f'Project {i}'} for i in range(17)]
        self.building.resolve(ds)
        self.building.edit_room(ds[0]['office_id'], 'rename', 'Особый офис')
        seats, catalog = self.building.load(), self.building.load_rooms()
        self.building.rename_building(2, '  Северный «А» <研发> & "Б"  ')
        self.assertEqual(self.building.load(), seats)
        self.assertEqual(self.building.load_rooms(), catalog)
        restarted = self.Building(self.path)
        title = 'Северный «А» <研发> & "Б"'
        self.assertEqual(restarted.load_building_names(), {'2': title})
        for snapshot in ([], list(reversed(ds))):
            rows = restarted.resolve(snapshot)
            self.assertEqual({r['id']: r['building_level'] for r in rows},
                             {rid: r['building_level'] for rid, r in catalog.items()})
            self.assertTrue(all(r['building_title'] == (title if r['building_level'] == 17 else 'Корпус 1')
                                for r in rows))
        self.assertEqual(restarted.load(), seats)
        self.assertEqual(restarted.load_rooms(), catalog)
        self.assertEqual(ds[0]['office_title'], 'Особый офис')
        restarted.rename_building(1, 'Южный')
        self.assertEqual(restarted.load_building_names(), {'1': 'Южный', '2': title})

    def test_invalid_building_names_numbers_and_unknown_buildings_do_not_mutate(self):
        self.building.resolve(self.residents(1))
        self.building.rename_building(1, 'Первый')
        files = (self.path, self.building.rooms_path, self.building.buildings_path)
        def contents():
            result = []
            for path in files:
                with open(path, 'rb') as stream:
                    result.append(stream.read())
            return result
        before = contents()
        cases = [(number, 'Имя') for number in (None, 0, -1, True, 1.0, '1', [], 2)]
        cases += [(1, name) for name in (None, '', '  ', 3, {}, 'я' * 61, 'А\nБ', '\tА',
                                          'А\r', 'А\x00Б', 'А\u2028Б', 'А\u202eБ')]
        for number, name in cases:
            with self.subTest(number=number, name=name):
                with self.assertRaises(ValueError):
                    self.building.rename_building(number, name)
                self.assertEqual(contents(), before)
        self.building.rename_building(1, 'я' * 60)
        self.assertEqual(self.building.load_building_names()['1'], 'я' * 60)

    def test_corrupt_building_names_are_not_overwritten_or_partially_migrated(self):
        ds = self.residents(1)
        self.building.resolve(ds)
        seats, rooms = self.building.load(), self.building.load_rooms()
        invalid = ['broken', '[]', 'null', '{"0":"A"}', '{"01":"A"}', '{"bad":"A"}',
                   '{"1":5}', '{"1":""}', '{"1":" A "}', '{"1":"A\\nB"}']
        for content in invalid:
            with self.subTest(content=content):
                with open(self.building.buildings_path, 'w', encoding='utf-8') as stream:
                    stream.write(content)
                with self.assertRaises(ValueError):
                    self.building.rename_building(1, 'Новое имя')
                with self.assertRaises(ValueError):
                    self.building.resolve(ds + [{'id': 'new', 'project': 'NEW'}])
                with open(self.building.buildings_path, encoding='utf-8') as stream:
                    self.assertEqual(stream.read(), content)
                self.assertEqual(self.building.load(), seats)
                self.assertEqual(self.building.load_rooms(), rooms)

    def post_building(self, body, headers=None):
        import io
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        ds = self.residents(1)
        self.building.resolve(ds)
        encoded = json.dumps(body).encode('utf-8')
        handler = self.srv.Handler.__new__(self.srv.Handler)
        handler.path = '/api/buildings'
        handler.rfile = io.BytesIO(encoded)
        handler.headers = {'Content-Length': str(len(encoded)), 'Content-Type': 'application/json',
                           'Host': '127.0.0.1:8772', 'Origin': 'http://127.0.0.1:8772'}
        handler.headers.update(headers or {})
        handler.server = SimpleNamespace(building=self.building, control=False, demo=True,
                                         logs=self.tmp, names=None, characters=self.characters)
        handler.send_error, handler.send_json = Mock(), Mock()
        with patch('artel_dashboard.handler.read_all', return_value={'daemons': ds}):
            handler.do_POST()
        return handler

    def test_delete_building_api_keeps_residents_and_rejects_nonempty(self):
        handler = self.post_building({'action': 'rename', 'building': 1, 'name': 'First'})
        room = self.building.create_room('Temporary', 'new')
        self.building.edit_room(room, 'delete')
        handler = self.post_building({'action': 'delete', 'building': 2})
        response = handler.send_json.call_args[0][0]
        self.assertEqual([b['number'] for b in response['buildings']], [1])
        self.assertEqual(len(response['daemons']), 1)
        handler = self.post_building({'action': 'delete', 'building': 1})
        self.assertIn('error', handler.send_json.call_args[0][0])

    def test_building_api_returns_current_state_when_daemon_control_disabled(self):
        handler = self.post_building({'action': 'rename', 'building': 1, 'name': 'Северный'})
        handler.send_error.assert_not_called()
        response = handler.send_json.call_args[0][0]
        self.assertFalse(response['control'])
        self.assertTrue(response['demo'])
        self.assertEqual(response['offices'][0]['building_title'], 'Северный')
        self.assertEqual(self.Building(self.path).load_building_names(), {'1': 'Северный'})

    def test_building_api_retains_same_origin_protection(self):
        for headers in ({'Origin': 'https://foreign.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            handler = self.post_building({'action': 'rename', 'building': 1, 'name': 'Северный'}, headers)
            handler.send_error.assert_called_once_with(403)
            handler.send_json.assert_not_called()
            self.assertEqual(self.building.load_building_names(), {})

    def test_building_api_rejects_invalid_requests_without_mutation(self):
        for body in ({'action': 'delete', 'building': 1, 'name': 'Северный'},
                     {'action': 'rename', 'building': 2, 'name': 'Северный'},
                     {'action': 'rename', 'building': 1, 'name': ''}):
            handler = self.post_building(body)
            self.assertIn('error', handler.send_json.call_args[0][0])
            self.assertEqual(self.building.load_building_names(), {})
        handler = self.post_building([])
        handler.send_error.assert_called_once_with(400)
        handler.send_json.assert_not_called()
