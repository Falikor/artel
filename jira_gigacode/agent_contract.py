"""Общий протокол исполнителя для первичной реализации и доработки."""
SUCCESS_MARKER = 'CODE_GENERATION_SUCCESS'
FAILURE_MARKERS = frozenset(('CODE_GENERATION_BLOCKED', 'CODE_GENERATION_FAILED'))

EXECUTION_CONTRACT = (
    '\nКонтракт Артели: передай именованному субагенту весь контекст этой задачи, ветку, базу, '
    'замечания и память. Выполни OpenSpec propose → apply → проверки → sync → archive '
    'по установленным инструкциям проекта; при повторе продолжай существующий change, '
    'при доработке архивированного создай связанный change. /opsx:* — команды ассистента, '
    'не shell; если прямой вызов недоступен, исполни читаемую локальную инструкцию workflow. '
    'Если OpenSpec или обязательные проверки недоступны — сообщи блокер. '
    'Не выполняй push, Jenkins и изменения Jira: это делает демон. '
    'Верни отчёт о реализации, проверках и пути архива. Блок LESSONS, если запрошен, '
    'должен быть перед финальным сигналом. Последняя непустая строка итогового ответа: '
    'CODE_GENERATION_SUCCESS только при полном успехе, иначе CODE_GENERATION_BLOCKED '
    'или CODE_GENERATION_FAILED. Не печатай сигналы в промежуточных сообщениях или через shell. '
    'При BLOCKED сформулируй конкретный вопрос или необходимое внешнее действие между отдельными '
    'строками BLOCKED_QUESTION_START и BLOCKED_QUESTION_END перед финальным сигналом: демон '
    'опубликует вопрос в Jira и будет ждать изменения постановки. '
    'Родитель обязан перенести результат субагента в окончательный ответ с тем же сигналом; '
    'не заменяй блокировку успехом и не цитируй другие сигналы.\n'
)


def result_status(output):
    """Standalone failure is conservative; quoted/mentioned success isn't a result."""
    lines = [line.strip() for line in (output or '').splitlines() if line.strip()]
    if 'CODE_GENERATION_FAILED' in lines:
        return 'failure'
    if 'CODE_GENERATION_BLOCKED' in lines:
        return 'blocked'
    if lines and lines[-1] == SUCCESS_MARKER:
        return 'success'
    return None
