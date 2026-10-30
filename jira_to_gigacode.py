#!/usr/bin/env python3
"""
JIRA → GigaCode Orchestrator (Autonomous Edition)

Мониторит задачи в статусах из jira.status_analysis, вызывает GigaCode CLI для генерации
кода (суб-агент), затем сам делает Git (ветка, коммит, пуш), деплой в Jenkins по лейблу
jenkins_{стенд}[_migration] и перевод задачи в один из статусов jira.status_ready.

Запуск: python3 jira_to_gigacode.py [путь_к_конфигу] [--check] [--dry-run]
  --check    проверить окружение (репозиторий, GigaCode, Jira, Jenkins) и выйти
  --dry-run  один проход «что бы сделал» без изменений в Jira, git и Jenkins

Один инстанс демона = один конфиг = один Jira-проект (или КЭ); для нескольких проектов
запускаются отдельные инстансы со своими конфигами и своими логами в logs/.

Код — в пакете jira_gigacode/ (карта модулей — в jira_gigacode/__init__.py).
Все демоны сразу, с перезапуском упавших: python3 artel.py start (см. README.md).
"""
from jira_gigacode.cli import main

if __name__ == "__main__":
    main()
