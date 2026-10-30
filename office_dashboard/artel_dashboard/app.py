"""Запуск дашборда: флаги командной строки, хранилища, демо-режим, HTTP-сервер."""
import argparse
import json
from pathlib import Path
import os
import tempfile

from .assets import discover_assets
from .common import BUNDLED_ASSETS, DEFAULT_ASSETS, DEFAULT_LOGS, ROOT
from .handler import make_server
from .stores import CHARACTER_ORDER, Characters, Names, Prices


def main():
    parser = argparse.ArgumentParser(description='Артель демонов: дашборд для JIRA → GigaCode')
    parser.add_argument('--launch-token', help=argparse.SUPPRESS)
    parser.add_argument('--logs', default=DEFAULT_LOGS, help=f'папка с логами и state-файлами (по умолчанию {DEFAULT_LOGS})')
    parser.add_argument('--assets', default=DEFAULT_ASSETS, help=f'папка ассетов (по умолчанию {BUNDLED_ASSETS})')
    parser.add_argument('--host', default='127.0.0.1', help='адрес (по умолчанию только локально)')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--demo', type=int, metavar='N', help='симуляция N демонов вместо реальных логов')
    parser.add_argument('--speed', type=float, default=1.0, help='ускорение симуляции (для --demo)')
    parser.add_argument('--names', default=os.path.join(ROOT, 'names.json'),
                        help='файл с именами демонов (по умолчанию office_dashboard/names.json)')
    parser.add_argument('--prices', default=os.path.join(ROOT, 'prices.json'),
                        help='файл цен за 1 млн токенов (правится во вкладке «Статистика»)')
    parser.add_argument('--characters', default=os.path.join(ROOT, 'characters.json'),
                        help='файл персонажей демонов (выбираются в панели демона)')
    parser.add_argument('--cat', action='store_true', help='впустить в офис кошку Кокошку')
    parser.add_argument('--no-control', action='store_true',
                        help='только смотреть: без кнопок «Остановить» / «Запустить» и «Проверить Jira сейчас»')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    from jira_gigacode.config import load_env_file
    from jira_gigacode.base import PROJECT_DIR
    load_env_file(os.environ.get('ENV_FILE') or os.path.join(PROJECT_DIR, 'tmp', '.env'))
    names = Names(os.path.abspath(os.path.expanduser(args.names)))
    prices = Prices(os.path.abspath(os.path.expanduser(args.prices)))
    characters = Characters(os.path.abspath(os.path.expanduser(args.characters)))
    logs = os.path.abspath(os.path.expanduser(args.logs))
    if args.demo:
        from demo import start_demo
        logs = tempfile.mkdtemp(prefix='office-demo-')
        if args.names == os.path.join(ROOT, 'names.json'):
            names.path = os.path.join(logs, 'names.json')  # демо не трогает боевой names.json
        if args.prices == os.path.join(ROOT, 'prices.json'):
            prices.path = os.path.join(logs, 'prices.json')
        if args.characters == os.path.join(ROOT, 'characters.json'):
            characters.path = os.path.join(logs, 'characters.json')
        start_demo(logs, args.demo, args.speed)
        print(f'Демо: {args.demo} демонов, state-файлы в {logs}')
    elif not os.path.isdir(logs):
        print(f'Папка логов пока не существует: {logs} — жду появления демонов.')

    server = make_server(args.host, args.port, logs, os.path.abspath(os.path.expanduser(args.assets)),
                         names, prices, characters, control=not args.no_control, demo=bool(args.demo),
                         cat=args.cat, verbose=args.verbose)
    assets = discover_assets(server.assets, server.cat)
    if assets.get('characters'):
        ids = [c['id'] for c in assets['characters']]
        characters.available = sorted(ids, key=lambda c: CHARACTER_ORDER.index(c) if c in CHARACTER_ORDER else len(ids))
    if assets.get('error'):
        print('ВНИМАНИЕ:', assets['error'])
    else:
        print(f"Ассеты: {server.assets}")
        print(f"Анимации персонажей: {assets['animationSet']} ({len(assets['characters'])} персонажей)")
    print(f'Логи: {logs}')
    print('Кокошка: ' + ('гуляет по офису' if args.cat else 'выключена (включить: --cat)'))
    if server.control and args.host not in ('127.0.0.1', 'localhost', '::1'):
        print('Дашборд открыт в сеть: логи и управление доступны по указанному адресу.')
    print(f'Дашборд: http://{args.host}:{args.port}/')
    # Register only real dashboards. Demo servers are intentionally unmanaged.
    from jira_gigacode import maintenance
    if not args.demo:
        maintenance.register('dashboard')
    record = Path(logs) / 'artel-dashboard.json'
    stop_file = Path(logs) / 'artel-dashboard-stop'
    if args.launch_token:
        maintenance.write(record, {'pid': os.getpid(), 'token': args.launch_token, 'port': args.port})
    server.daemon_threads = False
    server.timeout = .25
    try:
        while True:
            if args.launch_token and stop_file.exists() and stop_file.read_text(encoding='utf-8') == args.launch_token:
                break
            if not args.demo and maintenance.requested():
                server.maintenance_paused = True
                maintenance.checkpoint(before_wait=server.server_close)
            server.handle_request()
    except KeyboardInterrupt:
        pass

    finally:
        server.maintenance_paused = True
        server.server_close()
        if args.launch_token:
            try:
                if json.loads(record.read_text(encoding='utf-8')).get('token') == args.launch_token:
                    record.unlink()
            except FileNotFoundError:
                pass
