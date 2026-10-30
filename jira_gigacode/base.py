"""Общее для всех модулей пакета: корень проекта и логгер демона.

Модуль ничего не импортирует из пакета, поэтому его можно подключать откуда угодно
без циклических импортов.
"""
import logging
import os
import sys

# Корень проекта — папка, где лежат jira_to_gigacode.py, config/, logs/ и tmp/.env
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_DIR, 'logs')

# Стартовый лог до чтения конфига. Абсолютный путь: относительный создавал jira-agent.log
# в целевом репозитории, откуда он мог уехать в AI-ветку через git add .
# После чтения конфига logs.setup_logging() переключает вывод на файл инстанса.
LOG_FILE = os.path.join(PROJECT_DIR, 'jira-agent.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger('jira_gigacode')
