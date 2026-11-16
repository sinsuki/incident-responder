"""Turn a finding into the JSON report later agents can read."""

from __future__ import annotations

import datetime

from log_forensics.detect import Checkout, Finding, root_span, service_span
from log_forensics.load import Log, Span


def build_report(finding: Finding | None, checkouts: list[Checkout]) -> dict:
    if finding is None:
        return {
            "schema_version": 1,
            "incident": False,
            "service": None,
            "kind": None,
            "started_at_unix_nano": None,
            "summary": "No error-rate or latency spike found.",
            "stats": None,
            "claims": [],
            "tokens": {"input": 0, "output": 0},
        }
    onset = checkouts[finding.onset_index]
    return {
        "schema_version": 1,
        "incident": True,
        "service": finding.service,
        "kind": finding.kind,
        "started_at_unix_nano": onset.started_ns,
        "summary": _summary(finding, onset.started_ns),
        "stats": _stats(finding, len(checkouts)),
        "claims": _claims(finding, checkouts),
        "tokens": {"input": 0, "output": 0},
    }


def _summary(finding: Finding, started_ns: int) -> str:
    when = _format_ns(started_ns)
    if finding.kind == "error_rate":
        return (
            f"{finding.service} error rate rose from {_pct(finding.baseline_error_rate)} "
            f"to {_pct(finding.incident_error_rate)} at {when}. "
            f"The new log message is {finding.signature!r}."
        )
    slowed = (
        f"{finding.service} slowed from {_ms(finding.baseline_duration_ms)}ms "
        f"to {_ms(finding.incident_duration_ms)}ms at {when}."
    )
    if finding.kind == "timeout" and finding.signature:
        return f"{slowed} Callers logged {finding.signature!r}."
    return slowed


def _stats(finding: Finding, checkouts: int) -> dict:
    return {
        "baseline_duration_ms": _number(finding.baseline_duration_ms),
        "baseline_error_rate": round(finding.baseline_error_rate, 4),
        "checkouts_after": checkouts - finding.onset_index,
        "checkouts_before": finding.onset_index,
        "incident_duration_ms": _number(finding.incident_duration_ms),
        "incident_error_rate": round(finding.incident_error_rate, 4),
        "signature": finding.signature,
    }


def _claims(finding: Finding, checkouts: list[Checkout]) -> list[dict]:
    onset = checkouts[finding.onset_index]
    baseline = checkouts[finding.onset_index - 1]
    claims = [_onset_claim(finding, onset), _baseline_claim(finding, baseline)]
    if finding.kind == "timeout" and finding.signature:
        claims.append(_timeout_claim(onset, finding.signature))
    return claims


def _onset_claim(finding: Finding, onset: Checkout) -> dict:
    if finding.kind == "error_rate" and finding.signature:
        log = _body_log(onset, finding.signature)
        span = _span_by_id(onset, log.span_id)
    else:
        span = service_span(onset, finding.service)
        log = _span_log(onset, span)
    root = root_span(onset)
    duration = (span.end_ns - span.start_ns) // 1_000_000
    text = (
        f"Checkout trace {onset.trace_id} starts at {onset.started_ns}. "
        f"{finding.service} span {span.span_id} runs from {span.start_ns} to {span.end_ns} ({duration}ms). "
        f"Its log at {log.timestamp_ns} says {log.body!r}."
    )
    return {
        "text": text,
        "citations": [
            _span_citation(root, at="start"),
            _span_citation(span, at="start"),
            _span_citation(span, at="end"),
            _log_citation(log),
        ],
    }


def _baseline_claim(finding: Finding, checkout: Checkout) -> dict:
    span = service_span(checkout, finding.service)
    log = _info_log(checkout, span)
    duration = (span.end_ns - span.start_ns) // 1_000_000
    text = (
        f"Before the onset, {finding.service} span {span.span_id} runs from {span.start_ns} "
        f"to {span.end_ns} ({duration}ms). Its log at {log.timestamp_ns} says {log.body!r}."
    )
    return {
        "text": text,
        "citations": [
            _span_citation(span, at="start"),
            _span_citation(span, at="end"),
            _log_citation(log),
        ],
    }


def _timeout_claim(onset: Checkout, signature: str) -> dict:
    log = _body_log(onset, signature)
    span = _span_by_id(onset, log.span_id)
    text = (
        f"{log.service} logged {log.body!r} at {log.timestamp_ns} "
        f"on span {log.span_id} in trace {log.trace_id}."
    )
    return {
        "text": text,
        "citations": [
            _log_citation(log),
            _span_citation(span, at="end"),
        ],
    }


def _span_log(checkout: Checkout, span: Span) -> Log:
    matched = [log for log in checkout.logs if log.span_id == span.span_id]
    errors = [log for log in matched if log.severity == "ERROR"]
    if errors:
        return errors[0]
    if not matched:
        raise ValueError(f"span {span.span_id} has no log")
    return matched[0]


def _info_log(checkout: Checkout, span: Span) -> Log:
    infos = [log for log in checkout.logs if log.span_id == span.span_id and log.severity == "INFO"]
    if infos:
        return infos[0]
    matched = [log for log in checkout.logs if log.span_id == span.span_id]
    if not matched:
        raise ValueError(f"span {span.span_id} has no log")
    return matched[0]


def _body_log(checkout: Checkout, body: str) -> Log:
    for log in checkout.logs:
        if log.body == body:
            return log
    raise ValueError(f"log {body!r} is not on checkout {checkout.trace_id}")


def _span_by_id(checkout: Checkout, span_id: str) -> Span:
    for span in checkout.spans:
        if span.span_id == span_id:
            return span
    raise ValueError(f"span {span_id} is not on checkout {checkout.trace_id}")


def _log_citation(log: Log) -> dict:
    return {
        "file": "logs.jsonl",
        "line": log.line,
        "span_id": log.span_id,
        "timestamp_unix_nano": log.timestamp_ns,
        "trace_id": log.trace_id,
    }


def _span_citation(span: Span, *, at: str) -> dict:
    timestamp = span.start_ns if at == "start" else span.end_ns
    return {
        "file": "traces.jsonl",
        "line": span.line,
        "span_id": span.span_id,
        "timestamp_unix_nano": timestamp,
        "trace_id": span.trace_id,
    }


def _format_ns(timestamp_ns: int) -> str:
    seconds, nanos = divmod(timestamp_ns, 1_000_000_000)
    moment = datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S") + f".{nanos:09d}Z"


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _ms(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def _number(value: float):
    if value == int(value):
        return int(value)
    return value
