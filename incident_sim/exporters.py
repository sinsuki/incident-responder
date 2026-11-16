"""Write OpenTelemetry spans and logs to JSONL when the SDK shuts down."""

from __future__ import annotations

import json
from pathlib import Path

from opentelemetry.sdk._logs import ReadableLogRecord
from opentelemetry.sdk._logs.export import LogRecordExportResult, LogRecordExporter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id


def dumps(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def number(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def attributes(mapping) -> dict:
    if not mapping:
        return {}
    out = {}
    for key, value in dict(mapping).items():
        if isinstance(value, tuple):
            value = [number(item) for item in value]
        elif isinstance(value, float):
            value = number(value)
        out[str(key)] = value
    return out


def span_row(span: ReadableSpan) -> dict:
    parent = None
    if span.parent is not None and span.parent.span_id:
        parent = format_span_id(span.parent.span_id)
    status = span.status.status_code.name
    description = span.status.description or ""
    return {
        "attributes": attributes(span.attributes),
        "end_time_unix_nano": span.end_time,
        "kind": span.kind.name,
        "name": span.name,
        "parent_span_id": parent,
        "service": span.resource.attributes.get("service.name"),
        "span_id": format_span_id(span.context.span_id),
        "start_time_unix_nano": span.start_time,
        "status": status,
        "status_description": description,
        "trace_id": format_trace_id(span.context.trace_id),
    }


def log_row(record: ReadableLogRecord) -> dict:
    log = record.log_record
    trace_id = ""
    span_id = ""
    if log.trace_id:
        trace_id = format_trace_id(log.trace_id)
    if log.span_id:
        span_id = format_span_id(log.span_id)
    return {
        "attributes": attributes(log.attributes),
        "body": log.body,
        "service": record.resource.attributes.get("service.name"),
        "severity": log.severity_text,
        "span_id": span_id,
        "timestamp_unix_nano": log.timestamp,
        "trace_id": trace_id,
    }


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._rows: list[dict] = []
        self._closed = False

    def export(self, spans) -> SpanExportResult:
        for span in spans:
            self._rows.append(span_row(span))
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rows.sort(key=lambda row: (row["start_time_unix_nano"], row["name"], row["span_id"]))
        text = "".join(dumps(row) + "\n" for row in self._rows)
        self._path.write_text(text, encoding="utf-8")


class JsonlLogExporter(LogRecordExporter):
    def __init__(self, path: Path) -> None:
        self._path = path
        self._rows: list[dict] = []
        self._closed = False

    def export(self, batch) -> LogRecordExportResult:
        for record in batch:
            self._rows.append(log_row(record))
        return LogRecordExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rows.sort(
            key=lambda row: (row["timestamp_unix_nano"], row["service"], row["body"], row["span_id"])
        )
        text = "".join(dumps(row) + "\n" for row in self._rows)
        self._path.write_text(text, encoding="utf-8")
