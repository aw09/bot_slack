"""Application configuration values and helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List


@dataclass(frozen=True)
class Settings:
    allowed_channels: List[str]
    forward_channel_ids: List[str]
    bug_sheet_name: str
    thread_pool_max_workers: int | None
    user_id_slack_bot: str | None

    @staticmethod
    def _split_csv(value: str | None) -> List[str]:
        if not value:
            return []
        return [item.strip() for item in value.split(',') if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read environment variables once and expose strongly typed settings."""
    allowed_channels = Settings._split_csv(os.getenv("ALLOWED_CHANNELS"))
    forward_channels = Settings._split_csv(os.getenv("FORWARD_CHANNEL_ID"))
    bug_sheet_name = os.getenv("BUG_SHEET_NAME", "Bug List")

    raw_max_workers = os.getenv("THREAD_POOL_MAX_WORKERS")
    parsed_workers: int | None
    if raw_max_workers is None:
        parsed_workers = None
    else:
        try:
            parsed_workers = int(raw_max_workers)
        except ValueError:
            parsed_workers = None

    user_id_bot = os.getenv("USER_ID_SLACK_BOT")

    return Settings(
        allowed_channels=allowed_channels,
        forward_channel_ids=forward_channels,
        bug_sheet_name=bug_sheet_name,
        thread_pool_max_workers=parsed_workers,
        user_id_slack_bot=user_id_bot,
    )
