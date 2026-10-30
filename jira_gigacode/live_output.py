"""Last CLI session per daemon, independent of issue key and CLI purpose."""
from contextlib import contextmanager
from pathlib import Path
import time
import uuid


@contextmanager
def capture(reporter, issue, purpose):
    path = getattr(reporter, 'path', None)
    if not isinstance(path,str) or not path.endswith('-state.json') or not callable(getattr(reporter,'set_cli',None)):
        yield None
        return
    target = Path(path[:-len('-state.json')] + '-gigacode-live.log')
    info = dict(run=uuid.uuid4().hex, issue=issue, purpose=purpose or 'generation',
                started_at=time.time(), active=True)
    with target.open('w',encoding='utf-8') as log:
        reporter.set_cli(info)
        try:
            yield log
        finally:
            reporter.set_cli(dict(info,active=False,finished_at=time.time()))
