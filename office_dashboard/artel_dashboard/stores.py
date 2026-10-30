"""Что правится из интерфейса и хранится рядом с дашбордом: имена, персонажи, цены токенов."""
import json
import threading

from .common import write_json


class Names:
    """Имена демонов («HRPPA» → «Олег»): names.json рядом с дашбордом, правится из интерфейса."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            return {str(k).lower(): str(v) for k, v in data.items() if str(v).strip()}
        except Exception:
            return {}

    def set(self, project_id, name):
        with self.lock:
            data = self.load()
            name = (name or '').strip()[:40]
            if name:
                data[project_id] = name
            else:
                data.pop(project_id, None)
            write_json(self.path, dict(sorted(data.items())))
            return data


# Порядок, в котором персонажи раздаются демонам автоматически
CHARACTER_ORDER = ['worker_orange_yellow', 'worker_dark_purple', 'worker_brown_green', 'worker_black_charcoal',
                   'worker_blond_blue', 'worker_brown_red', 'manager_navy']


class Characters:
    """Персонаж офиса для каждого демона: characters.json рядом с дашбордом.

    Кто главнее: выбор на дашборде (source=user) → general.character в конфиге демона
    (приходит в state.json) → автоматическое назначение (source=auto). Автоматический персонаж
    назначается один раз, когда демон впервые появляется, — свободный, начиная с места по хэшу id, —
    и запоминается: добавление или удаление других демонов его не меняет."""

    def __init__(self, path, available=None):
        self.path = path
        self.available = list(available or CHARACTER_ORDER)
        self.lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            return {str(k).lower(): v for k, v in data.items()
                    if isinstance(v, dict) and v.get('character') in self.available}
        except Exception:
            return {}

    def _save(self, data):
        write_json(self.path, dict(sorted(data.items())))

    def set(self, daemon_id, character):
        """Выбор на дашборде; пустой character — вернуть автоматику (или выбор из конфига)."""
        if character and character not in self.available:
            raise ValueError(f'нет такого персонажа: {character}')
        with self.lock:
            data = self.load()
            if character:
                data[daemon_id] = {'character': character, 'source': 'user'}
            else:
                data.pop(daemon_id, None)
            self._save(data)
            return data

    def resolve(self, daemons):
        """Проставляет d['character'] и d['character_source'] каждому демону; новые автоназначения сохраняет."""
        if not self.available:
            return
        with self.lock:
            data, changed = self.load(), False
            taken = {v['character'] for v in data.values()}
            for d in sorted(daemons, key=lambda x: x['id']):
                own = data.get(d['id'])
                wanted = d.get('character')  # из конфига демона
                if own and own.get('source') == 'user':
                    d['character'], d['character_source'] = own['character'], 'dashboard'
                elif wanted in self.available:
                    d['character'], d['character_source'] = wanted, 'config'
                else:
                    if wanted:
                        d['character_warning'] = f'в конфиге неизвестный персонаж «{wanted}»'
                    if not own:
                        own = {'character': self._free(d['id'], taken, data), 'source': 'auto'}
                        data[d['id']] = own
                        taken.add(own['character'])
                        changed = True
                    d['character'], d['character_source'] = own['character'], 'auto'
            if changed:
                try:
                    self._save(data)
                except OSError:
                    pass

    def _free(self, daemon_id, taken, data=None):
        start = sum(ord(ch) for ch in daemon_id) % len(self.available)
        order = self.available[start:] + self.available[:start]
        return next((c for c in order if c not in taken),
                    min(order, key=lambda c: sum(v.get('character') == c for v in (data or {}).values())))


class Prices:
    """Цены за 1 млн токенов (вход, выход, кэш) и валюта: prices.json рядом с дашбордом, правятся во вкладке
    «Статистика». Стоимость задачи — оценка по расходу токенов, который сообщил GigaCode."""
    DEFAULT = {'input': 0.0, 'output': 0.0, 'cached': 0.0, 'currency': '₽'}

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def load(self):
        data = dict(self.DEFAULT)
        try:
            with open(self.path, encoding='utf-8') as f:
                raw = json.load(f)
            data.update(self.clean(raw))
        except Exception:
            pass
        return data

    @classmethod
    def clean(cls, raw):
        out = {}
        for k in ('input', 'output', 'cached'):
            try:
                v = float(str(raw.get(k, cls.DEFAULT[k])).replace(',', '.').replace(' ', ''))
            except (TypeError, ValueError):
                raise ValueError(f'цена {k} — не число')
            if v < 0 or v != v or v > 1e9:
                raise ValueError(f'цена {k} вне диапазона')
            out[k] = v
        currency = str(raw.get('currency', cls.DEFAULT['currency']) or '').strip()[:6]
        out['currency'] = currency or cls.DEFAULT['currency']
        return out

    def save(self, raw):
        data = self.clean(raw)
        with self.lock:
            write_json(self.path, data)
        return data


