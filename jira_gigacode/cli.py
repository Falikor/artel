"""Точка входа: флаги командной строки, проверка окружения и основной цикл опроса Jira.

Путь к конфигу: аргумент > env CONFIG_PATH > config/config.json рядом со скриптом.
Один инстанс демона = один конфиг = один Jira-проект (или один КЭ).
Секреты (токены Jira/Jenkins) — в tmp/.env рядом со скриптом; путь можно переопределить ENV_FILE.
"""
import logging
import os
import sys
import time

from . import __version__, log_archive, retro, retry, runtime
from .base import LOGS_DIR, PROJECT_DIR, logger
from .checks import run_startup_checks
from .config import (instance_key, load_config, load_env_file, resolve_param_bool, resolve_param_int,
                     validate_config)
from .dry_run import run_dry_run
from .logs import _issue_errors, setup_logging
from .pipeline import poll_once

USAGE = """Использование: python3 jira_to_gigacode.py [конфиг.json] [--check] [--dry-run] [--retro] [--version]
  --check    только проверить окружение (репозиторий, GigaCode, Jira, Jenkins) и выйти
  --dry-run  один проход «что бы сделал»: без генерации, пушей, деплоя, переводов и комментариев
  --retro    ретроспектива сейчас, не дожидаясь ночи (с --dry-run — только показать факты)
  --version  показать версию демона
Запуск всех демонов сразу, с перезапуском упавших: python3 artel.py start (см. python3 artel.py --help)"""


def parse_cli(argv):
    """(путь_к_конфигу | None, {'--check': bool, '--dry-run': bool}); неверные флаги — выход с кодом 2."""
    flags = {'--check': False, '--dry-run': False, '--retro': False}
    positional = []
    for arg in argv:
        if arg in ('-h', '--help'):
            print(USAGE)
            sys.exit(0)
        if arg == '--version':
            print(__version__)
            sys.exit(0)
        if arg in flags:
            flags[arg] = True
        elif arg.startswith('-'):
            print(f"Неизвестный флаг: {arg}\n{USAGE}", file=sys.stderr)
            sys.exit(2)
        else:
            positional.append(arg)
    if len(positional) > 1:
        print(f"Ожидается один путь к конфигу, получено: {positional}\n{USAGE}", file=sys.stderr)
        sys.exit(2)
    return (positional[0] if positional else None), flags


def main(argv=None):
    config_path, flags = parse_cli(sys.argv[1:] if argv is None else argv)
    load_env_file(os.environ.get('ENV_FILE') or os.path.join(PROJECT_DIR, 'tmp', '.env'))
    config_path = config_path or os.environ.get('CONFIG_PATH')
    check_only = flags['--check']
    runtime.DRY_RUN = flags['--dry-run'] or resolve_param_bool(None, 'DRY_RUN', {}, False)
    if config_path:
        logger.info(f"Используется конфиг: {config_path}")
    from .feature_control import apply
    config = apply(load_config(config_path))
    setup_logging(config, mode='check' if check_only else 'retro' if flags['--retro'] else ('dryrun' if runtime.DRY_RUN else 'agent'))
    validate_config(config)
    logging.getLogger().addHandler(_issue_errors)
    retry.set_pending_path(os.path.join(LOGS_DIR, f"{instance_key(config)}-pending-transitions.json"))

    errors, _warnings = run_startup_checks(config)
    if check_only:
        sys.exit(1 if errors else 0)
    if errors:
        logger.error("Старт отменён: исправьте ошибки выше. Проверить без запуска: "
                     "python3 jira_to_gigacode.py <конфиг> --check")
        sys.exit(1)
    if flags['--retro']:
        n = retro.run_retro(config, dry_run=runtime.DRY_RUN)
        logger.info(f"Ретроспектива завершена: задач {n}.")
        return
    if runtime.DRY_RUN:
        # Без отчёта для дашборда: пробный запуск не должен перетирать state.json живого демона
        run_dry_run(config)
        return

    run_daemon(config, config_path)


def run_daemon(config, config_path):
    """Основной цикл: опрос Jira → обработка задач → пауза до следующего опроса."""
    from . import maintenance
    maintenance.register("daemon")
    runtime.register_signal_handlers()
    poll_interval = resolve_param_int('general.poll_interval_seconds', 'POLL_INTERVAL', config, 600)
    retry_cooldown_sec = resolve_param_int('general.retry_cooldown_seconds', 'RETRY_COOLDOWN_SECONDS', config, 3600)
    runtime.state = runtime.create_state_reporter(config, config_path, poll_interval)
    runtime.watch_stop_flag(runtime.stop_flag_path(config))

    logger.info("=" * 60)
    logger.info(f"Запуск автономного мониторинга JIRA → GigaCode Orchestrator, версия {__version__}")
    logger.info("=" * 60)

    archive_logs = log_archive.Periodic(3600, config)   # ротация и архив логов — раз в час
    while runtime.running:
        maintenance.checkpoint(lambda: runtime.running)
        archive_logs()
        try:
            poll_once(config, retry_cooldown_sec)
            runtime.state.emit('idle', next_poll_at=time.time() + poll_interval)
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            runtime.state.emit('error', message=str(e))
        if not runtime.running:
            break
        _sleep_until_next_poll(poll_interval)

    logger.info("Цикл мониторинга завершён.")
    runtime.state.close()


def _sleep_until_next_poll(poll_interval):
    """Сон по секунде: SIGTERM завершает демона сразу, а двойной клик на дашборде
    («проверить Jira сейчас») прерывает ожидание."""
    deadline = time.time() + poll_interval
    from . import maintenance
    while runtime.running and time.time() < deadline:
        maintenance.checkpoint(lambda: runtime.running)
        if runtime.state.poke_requested():
            logger.info("Внеочередная проверка Jira по запросу с дашборда")
            break
        time.sleep(1)
