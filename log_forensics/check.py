"""Every citation must name a real line in the telemetry files."""

from __future__ import annotations

import json
from pathlib import Path

_FILES = {"logs.jsonl", "traces.jsonl"}


def check_citations(report: dict, directory: Path | str) -> list[str]:
    """Return one problem string per claim or citation that does not resolve.

    An empty list means every citation matches a line in traces.jsonl or
    logs.jsonl. A claim with no citations does not resolve. An incident with
    no claims does not resolve.
    """
    directory = Path(directory)
    problems = []
    claims = report.get("claims")
    if not isinstance(claims, list):
        return ["report claims are not a list"]
    if report.get("incident") and not claims:
        problems.append("incident report has no claims")
    for index, claim in enumerate(claims):
        problems.extend(_check_claim(directory, index, claim))
    return problems


def _check_claim(directory: Path, index: int, claim) -> list[str]:
    if not isinstance(claim, dict):
        return [f"claim {index} does not resolve: claim is not an object"]
    text = claim.get("text")
    if not isinstance(text, str) or not text.strip():
        return [f"claim {index} does not resolve: claim has no text"]
    citations = claim.get("citations")
    if not isinstance(citations, list) or not citations:
        return [f"claim {index} does not resolve: claim has no citations"]
    problems = []
    saw_log = False
    for citation in citations:
        problem = _resolve(directory, citation)
        if problem:
            problems.append(f"claim {index} does not resolve: {problem}")
            continue
        if isinstance(citation, dict) and citation.get("file") == "logs.jsonl":
            saw_log = True
    if not problems and not saw_log:
        problems.append(f"claim {index} does not resolve: claim has no log citation")
    return problems


def _resolve(directory: Path, citation) -> str | None:
    if not isinstance(citation, dict):
        return "citation is not an object"
    filename = citation.get("file")
    if filename not in _FILES:
        return f"citation file {filename!r} is not a trace or log line"
    line_number = citation.get("line")
    if isinstance(line_number, bool) or not isinstance(line_number, int) or line_number < 1:
        return "citation line is not a positive integer"
    path = directory / str(filename)
    if not path.is_file():
        return f"{filename} is missing"
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_number > len(lines):
        return f"{filename}:{line_number} is past the end of the file"
    try:
        record = json.loads(lines[line_number - 1])
    except json.JSONDecodeError:
        return f"{filename}:{line_number} is not JSON"
    if not isinstance(record, dict):
        return f"{filename}:{line_number} is not an object"
    trace_id = citation.get("trace_id") or ""
    span_id = citation.get("span_id") or ""
    if not trace_id and not span_id:
        return "citation has neither trace_id nor span_id"
    if trace_id and record.get("trace_id") != trace_id:
        return f"{filename}:{line_number} trace_id does not match"
    if span_id and record.get("span_id") != span_id:
        return f"{filename}:{line_number} span_id does not match"
    timestamp = citation.get("timestamp_unix_nano")
    if filename == "logs.jsonl":
        if timestamp != record.get("timestamp_unix_nano"):
            return f"{filename}:{line_number} timestamp does not match"
    elif timestamp not in {record.get("start_time_unix_nano"), record.get("end_time_unix_nano")}:
        return f"{filename}:{line_number} timestamp does not match span start or end"
    return None
