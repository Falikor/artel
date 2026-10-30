"""Task-level statistics; unknown measurements remain unknown, not zero."""
import math
import statistics
from .history import runs_cost


def percentile(values, fraction):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(tasks, prices):
    runs = [run for task in tasks for run in (task.get('runs') or [task])]
    duration = [t.get('total_seconds') for t in tasks]
    duration = [v for v in duration if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]
    measured_tokens = [r.get('tokens', {}).get('total') for r in runs if isinstance(r.get('tokens'), dict)]
    costs = [runs_cost(t, prices)[0] for t in tasks]
    finished = [t for t in tasks if t.get('result') in ('ok', 'warn')]
    return {'tasks': len(tasks), 'attempts': len(runs), 'completed': len(finished),
            'failed_attempts': sum(r.get('result') == 'fail' for r in runs),
            'first_pass': sum((t.get('attempts') or 1) == 1 for t in finished),
            'median_seconds': statistics.median(duration) if duration else None, 'p90_seconds': percentile(duration, .9),
            'tokens': sum(x for x in measured_tokens if isinstance(x, (int, float))),
            'token_coverage': sum(x is not None for x in measured_tokens),
            'cost': sum(c for c in costs if c is not None) if any(c is not None for c in costs) else None,
            'cost_coverage': sum(c is not None for c in costs), 'currency': prices.get('currency', '₽')}


def report(tasks, prices):
    groups = {}
    for task in tasks:
        groups.setdefault((task['id'], task.get('service') or ''), []).append(task)
    return {'totals': summarize(tasks, prices),
            'groups': [dict(summarize(rows, prices), id=k[0], service=k[1]) for k,rows in sorted(groups.items())]}
