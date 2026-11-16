"""Trace and span ids from a seeded generator, not the process RNG."""

from __future__ import annotations

import random

from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import INVALID_SPAN_ID, INVALID_TRACE_ID


class SeededIdGenerator(IdGenerator):
    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def generate_span_id(self) -> int:
        value = self._random.getrandbits(64)
        while value == INVALID_SPAN_ID:
            value = self._random.getrandbits(64)
        return value

    def generate_trace_id(self) -> int:
        value = self._random.getrandbits(128)
        while value == INVALID_TRACE_ID:
            value = self._random.getrandbits(128)
        return value
