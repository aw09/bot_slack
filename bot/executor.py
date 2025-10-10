"""Thread pool lifecycle management."""

from __future__ import annotations

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .config import get_settings

_EXECUTOR: Optional[ThreadPoolExecutor] = None
_EXECUTOR_LOCK = threading.Lock()


def _resolve_thread_pool_size() -> int:
    settings = get_settings()
    cpu_count = threading.active_count()  # proxy when os.cpu_count unavailable
    # fall back to os.cpu_count if available; default to 2 otherwise
    try:
        import os

        cpu_core_guess = os.cpu_count() or cpu_count or 1
    except Exception:  # pragma: no cover - defensive
        cpu_core_guess = cpu_count or 1

    conservative_default = max(2, min(4, cpu_core_guess))

    if settings.thread_pool_max_workers and settings.thread_pool_max_workers > 0:
        return settings.thread_pool_max_workers
    return conservative_default


def get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        with _EXECUTOR_LOCK:
            if _EXECUTOR is None:
                max_workers = _resolve_thread_pool_size()
                _EXECUTOR = ThreadPoolExecutor(
                    max_workers=max_workers,
                    thread_name_prefix="bot-worker",
                )
    return _EXECUTOR


def _shutdown_executor():
    global _EXECUTOR
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=False)


atexit.register(_shutdown_executor)
