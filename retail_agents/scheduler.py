"""Minimal cron-style scheduler (minute hour field only, e.g. '0 * * * *')."""
from __future__ import annotations

import time
from datetime import datetime


def _match(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        return value % int(field[2:]) == 0
    return value in {int(x) for x in field.split(",")}


def cron_due(expr: str, now: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron expression needs 5 fields")
    minute, hour, dom, month, dow = parts
    return (_match(minute, now.minute) and _match(hour, now.hour) and _match(dom, now.day)
            and _match(month, now.month) and _match(dow, now.isoweekday() % 7))


def run_loop(expr: str, job, clock=datetime.now, sleep=time.sleep, max_runs: int | None = None) -> int:
    """Calls job() once per matching minute. max_runs stops the loop (used in tests)."""
    runs, last = 0, None
    while max_runs is None or runs < max_runs:
        now = clock().replace(second=0, microsecond=0)
        if now != last and cron_due(expr, now):
            job(now)
            runs, last = runs + 1, now
        sleep(20)
    return runs
