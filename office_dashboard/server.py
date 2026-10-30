#!/usr/bin/env python3
"""
Артель демонов — дашборд для демонов jira_to_gigacode.py.

Читает logs/*-state.json (их пишет daemon_state.py), а для инстансов без
state-файла — разбирает logs/*-agent.log. Отдаёт страницу, ассеты из
пака LennoxStudio и поток состояний (SSE). Только stdlib.

  python3 office_dashboard/server.py                      # логи из ../logs
  python3 office_dashboard/server.py --demo 6             # симуляция 6 демонов
  python3 office_dashboard/server.py --port 8765 --logs /путь/к/logs

Код сервера — в пакете artel_dashboard/ (карта модулей — в его __init__.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from artel_dashboard.app import main  # noqa: E402
from artel_dashboard.assets import discover_assets  # noqa: E402,F401
from artel_dashboard.daemons import read_all  # noqa: E402,F401
from artel_dashboard.handler import Handler, make_server  # noqa: E402,F401
from artel_dashboard.history import group_tasks, read_history, read_proposals, read_tasks, runs_cost, task_cost  # noqa: E402,F401
from artel_dashboard import quality  # noqa: E402,F401
from artel_dashboard.stores import CHARACTER_ORDER, Characters, Names, Prices  # noqa: E402,F401

if __name__ == '__main__':
    main()
