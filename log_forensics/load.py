"""Read traces.jsonl and logs.jsonl, keeping the line number of each record."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Span:
    line: int
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    name: str
    kind: str
    start_ns: int
    end_ns: int
    status: str
    attributes: dict


@dataclass(frozen=True)
class Log:
    line: int
    timestamp_ns: int
    trace_id: str
    span_id: str
    service: str
    severity: str
    body: str


def load_directory(directory: Path) -> tuple[list[Span], list[Log]]:
    directory = Path(directory)
    spans = [_span(row, line) for line, row in _rows(directory / "traces.jsonl")]
    logs = [_log(row, line) for line, row in _rows(directory / "logs.jsonl")]
    return spans, logs


def _rows(path: Path) -> list[tuple[int, dict]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing {path.name} in {path.parent}")
    rows = []
    text = path.read_text(encoding="utf-8")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_number} is not JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{line_number} is not an object")
        rows.append((line_number, row))
    return rows


def _field(row: dict, key: str, filename: str, line: int):
    if key not in row:
        raise ValueError(f"{filename}:{line} is missing {key}")
    return row[key]


def _span(row: dict, line: int) -> Span:
    parent = row.get("parent_span_id")
    return Span(
        line=line,
        trace_id=str(_field(row, "trace_id", "traces.jsonl", line)),
        span_id=str(_field(row, "span_id", "traces.jsonl", line)),
        parent_span_id=None if parent is None else str(parent),
        service=str(_field(row, "service", "traces.jsonl", line)),
        name=str(_field(row, "name", "traces.jsonl", line)),
        kind=str(_field(row, "kind", "traces.jsonl", line)),
        start_ns=int(_field(row, "start_time_unix_nano", "traces.jsonl", line)),
        end_ns=int(_field(row, "end_time_unix_nano", "traces.jsonl", line)),
        status=str(_field(row, "status", "traces.jsonl", line)),
        attributes=dict(row.get("attributes") or {}),
    )


def _log(row: dict, line: int) -> Log:
    return Log(
        line=line,
        timestamp_ns=int(_field(row, "timestamp_unix_nano", "logs.jsonl", line)),
        trace_id=str(_field(row, "trace_id", "logs.jsonl", line)),
        span_id=str(_field(row, "span_id", "logs.jsonl", line)),
        service=str(_field(row, "service", "logs.jsonl", line)),
        severity=str(_field(row, "severity", "logs.jsonl", line)),
        body=str(_field(row, "body", "logs.jsonl", line)),
    )
