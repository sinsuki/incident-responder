"""Compare a baseline window with the requests after a candidate onset.

Latency uses each service's own span time, with child spans removed, so a
slow dependency is not also blamed on the callers waiting for it. An error
spike is a log message that does not appear in the baseline window and is
common afterward, and only when that service fails most of the later
requests. Healthy payments already declines some processor codes, so the
mere presence of errors is not an incident. The search looks for one change
that lasts until the end of the run.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from log_forensics.load import Log, Span

SERVICES = ("gateway", "orders", "inventory", "payments")
DEPTH = {"payments": 3, "inventory": 3, "orders": 2, "gateway": 1}

MIN_BEFORE = 3
MIN_AFTER = 4
LATENCY_DELTA_MS = 100
LATENCY_RATIO = 3
MESSAGE_RATE = 0.35
MESSAGE_COUNT = 4
OVERALL_RATE = 0.65
OVERALL_COUNT = 6
# A caller error and a callee slowdown are the same incident when their
# onsets land within this many checkouts of each other.
ONSET_SLACK = 2


@dataclass(frozen=True)
class Checkout:
    trace_id: str
    started_ns: int
    spans: tuple[Span, ...]
    logs: tuple[Log, ...]
    own_ms: dict[str, int]
    errors: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Finding:
    service: str
    kind: str
    onset_index: int
    signature: str | None
    baseline_duration_ms: float
    incident_duration_ms: float
    baseline_error_rate: float
    incident_error_rate: float


@dataclass(frozen=True)
class _Hit:
    service: str
    onset: int
    signature: str | None
    delta_ms: float
    message_rate: float


def build_checkouts(spans: list[Span], logs: list[Log]) -> list[Checkout]:
    by_trace: dict[str, list[Span]] = {}
    for span in spans:
        by_trace.setdefault(span.trace_id, []).append(span)
    logs_by_trace: dict[str, list[Log]] = {}
    for log in logs:
        logs_by_trace.setdefault(log.trace_id, []).append(log)

    checkouts = []
    for trace_id, trace_spans in by_trace.items():
        root = _one_root(trace_spans)
        trace_logs = tuple(logs_by_trace.get(trace_id, ()))
        errors: dict[str, tuple[str, ...]] = {}
        for log in trace_logs:
            if log.severity != "ERROR":
                continue
            errors[log.service] = errors.get(log.service, ()) + (log.body,)
        checkouts.append(
            Checkout(
                trace_id=trace_id,
                started_ns=root.start_ns,
                spans=tuple(trace_spans),
                logs=trace_logs,
                own_ms=_own_ms(trace_spans),
                errors=errors,
            )
        )
    checkouts.sort(key=lambda checkout: (checkout.started_ns, checkout.trace_id))
    return checkouts


def detect(checkouts: list[Checkout]) -> Finding | None:
    if len(checkouts) < MIN_BEFORE + MIN_AFTER:
        return None
    latency = _best_latency(checkouts)
    error = _best_error(checkouts)
    if latency and error and latency.service != error.service and abs(latency.onset - error.onset) <= ONSET_SLACK:
        kind = "timeout" if error.signature and "timed out" in error.signature else "latency"
        signature = error.signature if kind == "timeout" else None
        return _finding(checkouts, latency.service, kind, latency.onset, signature)
    if latency and (error is None or latency.onset <= error.onset):
        return _finding(checkouts, latency.service, "latency", latency.onset, None)
    if error:
        return _finding(checkouts, error.service, "error_rate", error.onset, error.signature)
    return None


def root_span(checkout: Checkout) -> Span:
    return _one_root(checkout.spans)


def service_span(checkout: Checkout, service: str) -> Span:
    if service == "inventory":
        return _one_span(checkout.spans, name="reserve")
    if service == "payments":
        return _one_span(checkout.spans, name="POST /charge", kind="SERVER")
    if service == "orders":
        return _one_span(checkout.spans, name="create_order")
    if service == "gateway":
        return _one_span(checkout.spans, name="POST /checkout")
    raise ValueError(f"unknown service {service}")


def _best_latency(checkouts: list[Checkout]) -> _Hit | None:
    hits = []
    for service in SERVICES:
        values = [float(checkout.own_ms[service]) for checkout in checkouts]
        onset = _best_onset(values, _latency_window)
        if onset is None:
            continue
        baseline = statistics.median(values[:onset])
        later = statistics.median(values[onset:])
        hits.append(_Hit(service, onset, None, float(later - baseline), 0.0))
    if not hits:
        return None
    return max(hits, key=lambda hit: (hit.delta_ms, DEPTH[hit.service]))


def _best_error(checkouts: list[Checkout]) -> _Hit | None:
    count = len(checkouts)
    hits = []
    for service in SERVICES:
        overall = [1.0 if checkout.errors.get(service) else 0.0 for checkout in checkouts]
        bodies = sorted({body for checkout in checkouts for body in checkout.errors.get(service, ())})
        best: tuple[tuple[float, float, int], int, str, float] | None = None
        for body in bodies:
            flags = [1.0 if body in checkout.errors.get(service, ()) else 0.0 for checkout in checkouts]
            for onset in range(MIN_BEFORE, count - MIN_AFTER + 1):
                if sum(flags[:onset]) != 0:
                    continue
                after = count - onset
                message_count = sum(flags[onset:])
                message_rate = message_count / after
                overall_count = sum(overall[onset:])
                overall_rate = overall_count / after
                if message_rate < MESSAGE_RATE or message_count < MESSAGE_COUNT:
                    continue
                if overall_rate < OVERALL_RATE or overall_count < OVERALL_COUNT:
                    continue
                cost = _sse(flags[:onset]) + _sse(flags[onset:])
                key = (cost, -message_rate, onset)
                if best is None or key < best[0]:
                    best = (key, onset, body, message_rate)
        if best is not None:
            hits.append(_Hit(service, best[1], best[2], 0.0, best[3]))
    if not hits:
        return None
    return max(hits, key=lambda hit: (DEPTH[hit.service], hit.message_rate))


def _best_onset(values: list[float], accept) -> int | None:
    count = len(values)
    best: tuple[float, int] | None = None
    for onset in range(MIN_BEFORE, count - MIN_AFTER + 1):
        before = values[:onset]
        after = values[onset:]
        if not accept(before, after):
            continue
        cost = _sse(before) + _sse(after)
        if best is None or cost < best[0] - 1e-9 or (abs(cost - best[0]) <= 1e-9 and onset < best[1]):
            best = (cost, onset)
    if best is None:
        return None
    return best[1]


def _latency_window(before: list[float], after: list[float]) -> bool:
    baseline = statistics.median(before)
    later = statistics.median(after)
    if baseline <= 0:
        return False
    return later - baseline >= LATENCY_DELTA_MS and later >= baseline * LATENCY_RATIO


def _finding(checkouts: list[Checkout], service: str, kind: str, onset: int, signature: str | None) -> Finding:
    before = checkouts[:onset]
    after = checkouts[onset:]
    return Finding(
        service=service,
        kind=kind,
        onset_index=onset,
        signature=signature,
        baseline_duration_ms=float(statistics.median([checkout.own_ms[service] for checkout in before])),
        incident_duration_ms=float(statistics.median([checkout.own_ms[service] for checkout in after])),
        baseline_error_rate=_rate(before, service),
        incident_error_rate=_rate(after, service),
    )


def _rate(checkouts: list[Checkout], service: str) -> float:
    if not checkouts:
        return 0.0
    errors = sum(1 for checkout in checkouts if checkout.errors.get(service))
    return errors / len(checkouts)


def _own_ms(spans: list[Span]) -> dict[str, int]:
    inventory = _duration(_one_span(spans, name="reserve"))
    payments = _duration(_one_span(spans, name="POST /charge", kind="SERVER"))
    client = _duration(_one_span(spans, name="POST /charge", kind="CLIENT"))
    orders = _duration(_one_span(spans, name="create_order"))
    gateway = _duration(_one_span(spans, name="POST /checkout"))
    return {
        "inventory": inventory,
        "payments": payments,
        "orders": orders - inventory - client,
        "gateway": gateway - orders,
    }


def _duration(span: Span) -> int:
    return (span.end_ns - span.start_ns) // 1_000_000


def _one_span(spans, *, name: str, kind: str | None = None) -> Span:
    found = [span for span in spans if span.name == name and (kind is None or span.kind == kind)]
    if len(found) != 1:
        raise ValueError(f"expected one {name} span, found {len(found)}")
    return found[0]


def _one_root(spans) -> Span:
    found = [span for span in spans if span.parent_span_id is None]
    if len(found) != 1:
        raise ValueError(f"expected one root span, found {len(found)}")
    return found[0]


def _sse(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values)
