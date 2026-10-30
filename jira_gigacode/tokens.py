"""Расход токенов GigaCode за прогон — для статистики Артели и отчёта в задаче.
"""
import glob
import json
import os
import re

from .config import resolve_param


_TOKEN_NUM = r'([\d][\d\s,._\u00a0]*)'

_TOKEN_PATTERNS = {
    'total': [r'(?i)total[ _-]?tokens?\s*[:=]\s*' + _TOKEN_NUM, r'(?i)tokens?\s*(?:used|total|spent)\s*[:=]\s*' + _TOKEN_NUM,
              r'(?i)(?:всего\s+)?токен(?:ов|ы)?\s*(?:всего|использовано|потрачено)?\s*[:=]\s*' + _TOKEN_NUM],
    'input': [r'(?i)(?:input|prompt)[ _-]?tokens?\s*[:=]\s*' + _TOKEN_NUM],
    'output': [r'(?i)(?:output|completion|candidates?)[ _-]?tokens?\s*[:=]\s*' + _TOKEN_NUM],
}


def _to_int(text):
    digits = re.sub(r'\D', '', str(text))
    return int(digits) if digits else None


_TOKEN_ALIASES = (
    ('input', ('input', 'prompt', 'input_tokens', 'inputtokens', 'prompt_tokens', 'prompttokencount')),
    ('output', ('output', 'candidates', 'output_tokens', 'outputtokens', 'completion_tokens', 'candidatestokencount')),
    ('cached', ('cached', 'cachedtokens', 'cached_tokens', 'cachedcontenttokencount')),
    ('total', ('total', 'total_tokens', 'totaltokens', 'totaltokencount')),
)


# Узлы-итоги прогона: если они есть, событийные счётчики рядом с ними не суммируются
_SUMMARY_KEYS = ('executionsummary', 'summary', 'total', 'totals', 'total_usage', 'totalusage')


def _direct_usage(node):
    """Счётчики токенов, лежащие прямо в этом словаре (не во вложенных)."""
    keys = {str(k).lower(): v for k, v in node.items()}
    found, hit = {'input': 0, 'output': 0, 'cached': 0, 'total': 0}, False
    for name, aliases in _TOKEN_ALIASES:
        for alias in aliases:
            value = keys.get(alias)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                found[name] = int(value)
                hit = True
                break
    if not hit:
        return None
    if not found['total']:
        found['total'] = found['input'] + found['output']
    return found


def _sum_usage(parts):
    total = {'input': 0, 'output': 0, 'cached': 0, 'total': 0}
    for part in parts:
        for k in total:
            total[k] += part.get(k) or 0
    return total


def _usage_from_json(obj):
    return _usage_from_json_ex(obj)[0]


def _usage_from_json_ex(obj):
    """(usage, from_summary). Расход токенов из JSON-статистики CLI без двойного счёта.

    Раньше суммировались счётчики на всех уровнях: итог прогона + разбивка по моделям
    (или итог + события) давали расход в 2 раза больше. Теперь:
      1) если в объекте есть узел-итог (executionSummary и т.п.) — берутся только итоги;
      2) иначе словарь со счётчиками прямо в себе считается итогом своего поддерева:
         внутрь него не спускаемся, а соседние ветки (модели a и b) складываются.
    """
    summaries = []

    def find_summaries(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if str(k).lower() in _SUMMARY_KEYS and isinstance(v, dict):
                    usage = _usage_tree(v)
                    if usage:
                        summaries.append(usage)
                        continue
                find_summaries(v)
        elif isinstance(node, list):
            for v in node:
                find_summaries(v)

    find_summaries(obj)
    if summaries:
        return _sum_usage(summaries), True
    return _usage_tree(obj), False


def _usage_tree(node):
    """Итог поддерева: счётчики узла, а без них — сумма итогов дочерних веток."""
    if isinstance(node, dict):
        own = _direct_usage(node)
        if own:
            return own
        parts = [u for u in (_usage_tree(v) for v in node.values()) if u]
    elif isinstance(node, list):
        parts = [u for u in (_usage_tree(v) for v in node) if u]
    else:
        return None
    return _sum_usage(parts) if parts else None


def extract_token_usage(output_text, config, started_at):
    """Расход токенов за прогон GigaCode. Источники по очереди:
    1) regex из конфига general.tokens_regex (группа 1 — всего токенов);
    2) JSON-статистика в выводе CLI (--output-format json);
    3) строки вида «Total tokens: 12 345» / «Токенов: …» в выводе;
    4) записи чата (--chat-recording): *.json в general.gigacode_chats_dir
       (по умолчанию ~/.gigacode, ~/.qwen, ~/.gemini), изменённые за время прогона.
    Возвращает {'input', 'output', 'cached', 'total', 'source'} или None."""
    text = output_text or ''
    custom = resolve_param('general.tokens_regex', 'GIGACODE_TOKENS_REGEX', config, None)
    if custom:
        m = None
        for m in re.finditer(custom, text):
            pass
        if m and _to_int(m.group(1)):
            return {'input': None, 'output': None, 'total': _to_int(m.group(1)), 'source': 'regex'}
    for line in reversed(text.strip().splitlines()[-50:]):
        line = line.strip()
        if line.startswith('{') and 'token' in line.lower():
            try:
                usage = _usage_from_json(json.loads(line))
            except ValueError:
                usage = None
            if usage:
                return dict(usage, source='json')
    tail = text[-20000:]
    usage = {}
    for name, patterns in _TOKEN_PATTERNS.items():
        for pattern in patterns:
            matches = re.findall(pattern, tail)
            if matches and _to_int(matches[-1]):
                usage[name] = _to_int(matches[-1])
                break
    if usage.get('total') or (usage.get('input') and usage.get('output')):
        usage.setdefault('total', (usage.get('input') or 0) + (usage.get('output') or 0))
        return {'input': usage.get('input'), 'output': usage.get('output'), 'total': usage['total'], 'source': 'text'}
    # 4) записи чатов (--chat-recording). У GigaCode это projects/<слаг репо>/chats/<uuid>.jsonl:
    #    по событию в строке, итог прогона суб-агента — в executionSummary (inputTokens/
    #    outputTokens/totalTokens). Ищем сначала в папке проекта репозитория (repo_path),
    #    чтобы не приплюсовать параллельные сессии в других репо; иначе — по всем корням.
    roots = resolve_param('general.gigacode_chats_dir', 'GIGACODE_CHATS_DIR', config, None)
    home = os.path.expanduser('~')
    if roots:
        roots = [roots] if isinstance(roots, str) else roots
    else:
        tool_dirs = ['.gigacode', '.qwen', '.gemini']
        repo = resolve_param('general.repo_path', 'REPO_PATH', config, None)
        roots = []
        if repo:
            slug = os.path.abspath(os.path.expanduser(repo)).replace(os.sep, '-').replace('_', '-')
            roots = [os.path.join(home, d, 'projects', slug) for d in tool_dirs]
            roots = [r for r in roots if os.path.isdir(r)]
        if not roots:
            roots = [os.path.join(home, d) for d in tool_dirs]

    def _usage_lines(f):
        for line in f:
            if 'token' not in line.lower():
                continue
            try:
                usage, is_summary = _usage_from_json_ex(json.loads(line))
            except ValueError:
                continue
            if usage:
                yield usage, is_summary

    total = {'input': 0, 'output': 0, 'cached': 0, 'total': 0}
    hit = False
    for root in roots:
        for path in set(glob.glob(os.path.join(os.path.expanduser(root), '**', '*.json'), recursive=True)
                        + glob.glob(os.path.join(os.path.expanduser(root), '**', '*.jsonl'), recursive=True)):
            low = path.lower()
            if 'chat' not in low and 'session' not in os.path.basename(low):
                continue
            try:
                if os.path.getmtime(path) < started_at - 5 or os.path.getsize(path) > 50 * 1024 * 1024:
                    continue
                with open(path, encoding='utf-8') as f:
                    if path.endswith('.jsonl'):
                        # Строки-итоги (executionSummary) уже включают расход событий своей
                        # сессии: если они есть, события не суммируются, иначе — сумма событий
                        summary_parts, event_parts = [], []
                        for u, is_summary in _usage_lines(f):
                            (summary_parts if is_summary else event_parts).append(u)
                        parts = summary_parts or event_parts
                        usage = _sum_usage(parts) if parts else None
                    else:
                        usage = _usage_from_json(json.load(f))
            except (OSError, ValueError):
                continue
            if usage:
                hit = True
                for k in total:
                    total[k] += usage.get(k) or 0
    if hit and total['total']:
        return dict(total, source='chat-recording')
    return None
