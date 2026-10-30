"""Временные копии репозитория (git worktree) для прогонов, которым нельзя трогать рабочий клон.

Ревьюер и исследователь задач работают в отдельной папке, отведённой от нужной ветки:
что бы агент там ни записал, после прогона папка удаляется, а основной клон с работой
демона остаётся нетронутым.
"""
import contextlib
import os
import shutil
import subprocess
import tempfile

from .base import logger


class WorktreeError(RuntimeError):
    pass


@contextlib.contextmanager
def temp_worktree(repo, ref, label):
    """Папка с detached-копией ref; после выхода — удаляется вместе с записью worktree."""
    path = tempfile.mkdtemp(prefix=f"artel-{label}-")
    proc = subprocess.run(['git', 'worktree', 'add', '--detach', '--force', path, ref],
                          cwd=repo, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise WorktreeError(f"не удалось создать временную копию {ref}: {proc.stderr.strip()}")
    try:
        yield path
    finally:
        removed = subprocess.run(['git', 'worktree', 'remove', '--force', path],
                                 cwd=repo, capture_output=True, text=True, timeout=120)
        if removed.returncode != 0:
            logger.warning(f"Не удалось удалить временную копию {path}: {removed.stderr.strip()}")
        shutil.rmtree(path, ignore_errors=True)
        subprocess.run(['git', 'worktree', 'prune'], cwd=repo, capture_output=True, timeout=60)


def worktree_is_clean(path):
    """True — агент ничего не изменил во временной копии (для лога: ревьюер должен только читать)."""
    proc = subprocess.run(['git', 'status', '--porcelain'], cwd=path, capture_output=True, text=True, timeout=30)
    return proc.returncode == 0 and not proc.stdout.strip()


def worktree_exists(path):
    return os.path.isdir(path)
