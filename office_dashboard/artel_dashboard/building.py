"""Persistent room/seat and appearance assignments, independent of browser storage."""
import hashlib
import json
import threading
import unicodedata

from .common import write_json

CAPACITY = 10
VARIANTS = 6
BUILDING_FLOORS = 16


class Building:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.rooms_path = path + '.rooms.json'
        self.buildings_path = path + '.buildings.json'

    @staticmethod
    def _building_name(name):
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 60
                or any(unicodedata.category(char)[0] == 'C'
                       or unicodedata.category(char) in ('Zl', 'Zp') for char in name)):
            raise ValueError('Название корпуса: от 1 до 60 символов, без переносов строк и управляющих символов')
        return name.strip()

    def load_building_names(self):
        try:
            with open(self.buildings_path, encoding='utf-8') as f:
                names = json.load(f)
            if not isinstance(names, dict):
                raise ValueError('Некорректный каталог названий корпусов')
            for number, name in names.items():
                if (not number.isascii() or not number.isdecimal()
                        or int(number) < 1 or str(int(number)) != number
                        or self._building_name(name) != name):
                    raise ValueError('Некорректный каталог названий корпусов')
            return names
        except FileNotFoundError:
            return {}

    def rename_building(self, number, name):
        if type(number) is not int or number < 1:
            raise ValueError('Некорректный номер корпуса')
        title = self._building_name(name)
        with self.lock:
            catalog = self.load_rooms()
            existing = {(meta['building_level'] - 1) // BUILDING_FLOORS + 1
                        for meta in catalog.values() if isinstance(meta, dict)
                        and type(meta.get('building_level')) is int and meta['building_level'] > 0}
            if number not in existing:
                raise ValueError('Корпус не найден')
            names = self.load_building_names()
            names[str(number)] = title
            write_json(self.buildings_path, names)

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('Некорректный файл рассадки')
            return data
        except FileNotFoundError:
            return {}

    def load_rooms(self):
        try:
            with open(self.rooms_path, encoding='utf-8') as f:
                rooms = json.load(f)
            if not isinstance(rooms, dict):
                raise ValueError('Некорректный каталог офисов')
            return rooms
        except FileNotFoundError:
            return {}

    def edit_room(self, room, action, name=None):
        with self.lock:
            rooms = self.load_rooms()
            if room not in rooms:
                raise ValueError('Офис не найден')
            if action == 'rename':
                if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
                    raise ValueError('Название офиса: от 1 до 60 символов')
                rooms[room]['title'] = name.strip()
            elif action == 'delete':
                if any('group' in v and 'seat' in v and self.room_id(v['group'], v['seat']) == room
                       for v in self.load().values()):
                    raise ValueError('В офисе есть демоны или закреплённые места. Сначала переселите их.')
                del rooms[room]
            else:
                raise ValueError('Неизвестное действие')
            write_json(self.rooms_path, rooms)

    def set_variant(self, daemon_id, variant):
        if type(variant) is not int or not 0 <= variant < VARIANTS:
            raise ValueError('Неизвестная палитра персонажа')
        with self.lock:
            data = self.load()
            data.setdefault(daemon_id, {})['variant'] = variant
            write_json(self.path, data)

    @staticmethod
    def room_id(group, seat):
        return hashlib.sha256(group.encode()).hexdigest()[:16] + '-' + str(seat // CAPACITY)

    def move(self, daemon_id, room=None, name=None):
        with self.lock:
            data = self.load()
            if daemon_id not in data:
                raise ValueError('Демон не найден')
            own = data[daemon_id]
            if room == 'auto':
                own.pop('manual', None)
                own.pop('group', None)
                own.pop('seat', None)
            else:
                if name is not None:
                    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
                        raise ValueError('Название офиса: от 1 до 60 символов')
                    group, floor = json.dumps(['Офисы', name.strip()], ensure_ascii=False), 0
                else:
                    target = self.load_rooms().get(room)
                    if target is None:
                        raise ValueError('Офис не найден')
                    group, floor = target['group'], target['floor']
                if own.get('group') == group and own.get('seat', -1) // CAPACITY == floor:
                    own['manual'] = True
                else:
                    used = {v['seat'] for k, v in data.items() if k != daemon_id and v.get('group') == group and 'seat' in v}
                    seat = next((n for n in range(floor * CAPACITY, (floor + 1) * CAPACITY) if n not in used), None)
                    if seat is None:
                        raise ValueError('В офисе нет свободных мест. Создайте новый офис.')
                    own.update(group=group, seat=seat, manual=True)
            write_json(self.path, data)

    def resolve(self, daemons):
        with self.lock:
            building_names = self.load_building_names()
            data = self.load()
            before = json.dumps(data, sort_keys=True)
            occupied = {(v.get('group'), v.get('seat')) for v in data.values() if 'seat' in v}
            looks = {(v.get('character'), v.get('variant')) for v in data.values()}
            catalog = self.load_rooms()
            catalog_before = json.dumps(catalog, sort_keys=True)
            # Retain rooms after the last resident moves, including reserved seats.
            for v in data.values():
                if 'group' not in v or 'seat' not in v:
                    continue
                project, service = json.loads(v['group'])
                floor = v['seat'] // CAPACITY
                rid = self.room_id(v['group'], v['seat'])
                catalog.setdefault(rid, {'id': rid, 'group': v['group'], 'floor': floor,
                    'project': project, 'service': service,
                    'title': project + (' · ' + service if service else '') + f' / офис {floor + 1}'})
            rooms = {}
            for d in sorted(daemons, key=lambda x: x['id']):
                project = str(d.get('project') or 'Без проекта')
                # Only stable configuration metadata; current task's detail.service is transient.
                service = str(d.get('office_group') or d.get('service') or '')
                group = json.dumps([project, service], ensure_ascii=False)
                own = data.setdefault(d['id'], {})
                if own.get('manual') and own.get('group'):
                    group = own['group']
                    project, service = json.loads(group)
                if own.get('group') != group or type(own.get('seat')) is not int or own['seat'] < 0:
                    seat = 0
                    while (group, seat) in occupied:
                        seat += 1
                    own.update(group=group, seat=seat)
                    occupied.add((group, seat))
                char = d.get('character')
                if type(own.get('variant')) is not int or not 0 <= own['variant'] < VARIANTS:
                    start = int(hashlib.sha256(d['id'].encode()).hexdigest()[:8], 16) % VARIANTS
                    options = [(start + n) % VARIANTS for n in range(VARIANTS)]
                    own['variant'] = next((v for v in options if (char, v) not in looks), options[0])
                own['character'] = char
                looks.add((char, own['variant']))
                floor, slot = divmod(own['seat'], CAPACITY)
                room_id = hashlib.sha256(group.encode()).hexdigest()[:16] + '-' + str(floor)
                title = project + (' · ' + service if service else '') + f' / офис {floor + 1}'
                catalog.setdefault(room_id, {'id': room_id, 'group': group, 'floor': floor,
                    'project': project, 'service': service, 'title': title})
                title = catalog[room_id]['title']
                d.update(office_id=room_id, office_title=title, office_slot=slot, appearance=own['variant'], office_manual=bool(own.get('manual')))
                rooms.setdefault(room_id, {'id': room_id, 'title': title, 'capacity': CAPACITY,
                                          'project': project, 'service': service, 'daemons': []})['daemons'].append(d['id'])
            if json.dumps(data, sort_keys=True) != before:
                write_json(self.path, data)
            next_level = max((m.get('building_level', 0) for m in catalog.values()
                              if type(m.get('building_level')) is int and m['building_level'] > 0), default=0) + 1
            for rid, meta in catalog.items():
                if type(meta.get('building_level')) is not int or meta['building_level'] < 1:
                    meta['building_level'] = next_level
                    next_level += 1
                r = rooms.setdefault(rid, {**meta, 'capacity': CAPACITY, 'daemons': []})
                r['title'] = meta['title']
                r['building_level'] = meta['building_level']
                number = (meta['building_level'] - 1) // BUILDING_FLOORS + 1
                r['building_title'] = building_names.get(str(number), f'Корпус {number}')
                r['occupied'] = sum(1 for v in data.values() if 'group' in v and 'seat' in v
                                    and self.room_id(v['group'], v['seat']) == rid)
            if json.dumps(catalog, sort_keys=True) != catalog_before:
                write_json(self.rooms_path, catalog)
            return sorted(rooms.values(), key=lambda r: (r['project'], r['service'], r['title']))
