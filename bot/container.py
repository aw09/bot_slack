"""Centralised construction of application services."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, TypeVar

from slack_bot import SlackBot
from gemini_hook import GeminiAnalyzer
from spreadsheet import SpreadsheetManager
from spreadsheetbug import SpreadsheetBugManager

T = TypeVar("T")


class LazyProxy:
    """Thread-safe lazy loader for heavyweight singletons."""

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._instance: T | None = None
        self._lock = threading.Lock()

    def _get_instance(self) -> T:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return self._instance

    def __getattr__(self, item):
        return getattr(self._get_instance(), item)

    def __call__(self) -> T:
        return self._get_instance()


@dataclass(frozen=True)
class ServiceContainer:
    slack_bot: LazyProxy
    gemini_analyzer: LazyProxy
    spreadsheet_manager: LazyProxy
    spreadsheet_bug_manager: LazyProxy


container = ServiceContainer(
    slack_bot=LazyProxy(SlackBot),
    gemini_analyzer=LazyProxy(GeminiAnalyzer),
    spreadsheet_manager=LazyProxy(SpreadsheetManager),
    spreadsheet_bug_manager=LazyProxy(SpreadsheetBugManager),
)
