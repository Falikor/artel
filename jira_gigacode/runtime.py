"""Изменяемое состояние процесса демона, общее для всех модулей.

Обращаться к нему нужно через модуль (runtime.DRY_RUN, runtime.state), а не через
`from .runtime import DRY_RUN`: иначе модуль увидит значение на момент импорта.
"""
import inspect
import os
import signal
import threading
import time

from .base import LOGS_DIR, logger
from .config import instance_key, normalized_ci_id, resolve_param

# Состояние для офис-дашборда (logs/{КЭ}-state.json). Без модуля демон работает как раньше.
try:
    from daemon_state import NullReporter, StateReporter
except ImportError:
    StateReporter = None

    class NullReporter:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

# False — получен SIGTERM/SIGINT: основной цикл завершается после текущего шага
running = True

# --dry-run: один проход «что бы сделал» — без генерации, пушей, деплоя, переводов и комментариев
DRY_RUN = False

# Отчёт о состоянии для дашборда Артели; до старта (и в dry-run) — заглушка
state = NullReporter()


def create_state_reporter(config, config_path, poll_interval):
    if StateReporter is None:
        logger.warning("daemon_state.py не найден — состояние для дашборда не пишется.")
        return NullReporter()
    from . import __version__
    try:
        kwargs = {
            'config_path': config_path, 'poll_interval': poll_interval,
            # Имя демона на дашборде (например «Олег»); без него показывается ключ проекта
            'name': resolve_param('general.name', 'DAEMON_NAME', config, None),
            'jira_url': resolve_param('jira.url', 'JIRA_URL', config, None),
            # КЭ сервиса в реестре (например CI15172563) — виден на карточке демона
            'ci_id': normalized_ci_id(config),
            'daemon_version': __version__,
        }
        # Старые версии daemon_state.py не знают новых параметров — передаём только известные
        accepted = inspect.signature(StateReporter).parameters
        reporter = StateReporter(
            os.path.join(LOGS_DIR, f"{instance_key(config)}-state.json"),
            resolve_param('jira.project', None, config, None),
            **{k: v for k, v in kwargs.items() if k in accepted})
        if isinstance(getattr(reporter, 'state', None), dict):
            if 'daemon_version' not in accepted:
                reporter.state['daemon_version'] = __version__
            # Что демон умеет по запросу с дашборда: poke — «проверь Jira сейчас», stop — остановиться
            reporter.state['features'] = list(FEATURES)
            # Персонаж офиса из конфига (general.character); выбор на дашборде главнее
            for field in ('service', 'office_group'):
                value = resolve_param('general.' + field, None, config, None)
                if value:
                    reporter.state[field] = str(value)
            character = resolve_param('general.character', None, config, None)
            if character:
                reporter.state['character'] = str(character)
        reporter.attach_logging()
        logger.info(f"Состояние для дашборда: {reporter.path}")
        return reporter
    except Exception as e:
        logger.warning(f"Не удалось включить отчёт о состоянии: {e}")
        return NullReporter()


FEATURES = ('poke', 'stop', 'feature-control', 'prompt-control', 'live-cli', 'cli-events', 'task-dependencies')


# --- остановка по запросу с дашборда ---
def stop_flag_path(config):
    return os.path.join(LOGS_DIR, f"{instance_key(config)}-stop")


def watch_stop_flag(path, interval=1.0):
    """Фоновая проверка флажка logs/{КЭ|проект}-stop (его ставит дашборд кнопкой «Остановить»).
    Флажок действует как SIGTERM: GigaCode прерывается, демон завершается за секунды.
    Старый флажок, оставшийся с прошлого запуска, удаляется сразу — он не должен остановить новый."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Не удалось удалить старый флажок остановки {path}: {e}")

    def loop():
        global running
        while running:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
                logger.warning("Остановка по запросу с дашборда.")
                running = False
                return
            time.sleep(interval)
    thread = threading.Thread(target=loop, name='stop-flag', daemon=True)
    thread.start()
    return thread


# Этапы, которых может не знать старый daemon_state.py, и чем их заменить
_STAGE_FALLBACK = {'reviewing': 'jira', 'rework': 'git', 'exploring': 'polling', 'retro': 'polling'}


def emit(stage, issue=None, **detail):
    """state.emit, переживающий старый daemon_state.py: незнакомый этап заменяется близким."""
    try:
        state.emit(stage, issue, **detail)
    except ValueError:
        fallback = _STAGE_FALLBACK.get(stage)
        if fallback:
            state.emit(fallback, issue, activity=stage, **detail)


def signal_handler(signum, frame):
    global running
    if not running:
        return
    logger.info(f"Получен сигнал {signum}, завершение...")
    running = False


def register_signal_handlers():
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except ValueError:
        pass
