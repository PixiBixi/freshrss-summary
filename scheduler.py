"""Background scheduling utilities for FreshRSS Summary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


async def run_every(coro_fn: Callable[..., Coroutine], interval_seconds: float, *args: Any) -> None:
    """Run coro_fn(*args) at fixed intervals, swallowing non-cancellation exceptions."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await coro_fn(*args)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled task %s failed", coro_fn.__name__)


async def run_daily_at(
    coro_fn: Callable[..., Coroutine], hour: int, tz_name: str, *args: Any
) -> None:
    """Run coro_fn(*args) once per day at the given hour in tz_name timezone."""
    import datetime
    import zoneinfo

    tz = zoneinfo.ZoneInfo(tz_name)
    while True:
        now = datetime.datetime.now(tz)
        next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += datetime.timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            await coro_fn(*args)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily task %s failed", coro_fn.__name__)
