#!/usr/bin/env python3
"""Супервизор Артели: запуск, перезапуск и статус всех демонов из config/*.json.

    python3 artel.py start | run | status | restart [имя… | --outdated] | stop | check

Подробности — python3 artel.py --help и jira_gigacode/supervisor.py.
"""
import sys

from jira_gigacode.supervisor import main

if __name__ == "__main__":
    sys.exit(main())
