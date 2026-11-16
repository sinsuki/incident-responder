"""Simulated clock. Scenarios advance this instead of sleeping."""

from __future__ import annotations

import datetime

# 2026-01-15 15:00:00 UTC. Every run starts here so timestamps do not depend on the wall clock.
START_NS = int(datetime.datetime(2026, 1, 15, 15, 0, tzinfo=datetime.timezone.utc).timestamp()) * 1_000_000_000

MS = 1_000_000
GAP_NS = 100 * MS


class Clock:
    def __init__(self) -> None:
        self._ns = 0

    def set(self, ns: int) -> None:
        self._ns = ns

    def now_ns(self) -> int:
        return self._ns
