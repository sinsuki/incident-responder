"""Build the root-cause report from the three upstream reports.

Each section is a list of claims. A claim is one sentence that names the
log timestamp, trace or span id, commit, file:line, or runbook section it
cites. Facts come from those upstream citations. ground_truth.json is not
read.
"""

from __future__ import annotations

import copy
import re

from orchestrator.tokens import account

_BODY = re.compile(r"(?:says|logged) '([^']*)'")
_TELEMETRY = {"logs.jsonl", "traces.jsonl"}
_SECTIONS = ("summary", "impact", "timeline", "root_cause", "evidence", "mitigation")


def build_report(forensics: dict, archaeology: dict, runbook: dict) -> dict:
    if not isinstance(forensics, dict) or not isinstance(archaeology, dict) or not isinstance(runbook, dict):
        raise ValueError("upstream report is not an object")
    if not forensics.get("incident"):
        return _quiet(forensics, archaeology, runbook)
    service, kind = _service_kind(forensics)
    claims = _claim_list(forensics, "forensics")
    if len(claims) < 2:
        raise ValueError("forensics report does not have an onset and a baseline claim")
    onset_log = _require_log(claims[0])
    sections = {name: [] for name in _SECTIONS}
    sections["summary"] = _summary(service, kind, onset_log, archaeology, runbook)
    sections["impact"] = _impact(claims)
    sections["timeline"] = _timeline(claims)
    sections["root_cause"] = _root_cause(archaeology, onset_log)
    sections["evidence"] = _evidence(claims, archaeology)
    sections["mitigation"] = _mitigation(forensics, archaeology, runbook, onset_log)
    return {
        "schema_version": 1,
        "incident": True,
        "service": service,
        "kind": kind,
        "started_at_unix_nano": forensics.get("started_at_unix_nano"),
        "commit": _commit(archaeology),
        "runbook": runbook.get("runbook"),
        "runbook_file": runbook.get("runbook_file"),
        "matched": bool(runbook.get("matched")),
        "sections": sections,
        "steps": copy.deepcopy(runbook.get("steps") or []),
        "tokens": account(forensics, archaeology, runbook, {"input": 0, "output": 0}),
    }


def _quiet(forensics: dict, archaeology: dict, runbook: dict) -> dict:
    return {
        "schema_version": 1,
        "incident": False,
        "service": None,
        "kind": None,
        "started_at_unix_nano": None,
        "commit": None,
        "runbook": None,
        "runbook_file": None,
        "matched": False,
        "sections": {
            "summary": [{"text": "No error-rate or latency spike found.", "citations": []}],
            "impact": [],
            "timeline": [],
            "root_cause": [],
            "evidence": [],
            "mitigation": [],
        },
        "steps": [],
        "tokens": account(forensics, archaeology, runbook, {"input": 0, "output": 0}),
    }


def _summary(service: str, kind: str, onset_log: dict, archaeology: dict, runbook: dict) -> list[dict]:
    log = _copy_telemetry(onset_log)
    sentences = [
        _claim(
            f"{service.capitalize()} {kind} is on trace {log['trace_id']} at log timestamp {log['timestamp_unix_nano']}.",
            [log],
        )
    ]
    lead = _first_code(archaeology)
    if lead is not None:
        code = _copy_code(lead)
        sentences.append(
            _claim(
                f"The implicated line is {code['file']}:{code['line']} in commit {code['commit']}.",
                [code],
            )
        )
    if runbook.get("matched"):
        section = _first_runbook_citation(runbook)
        if section is not None:
            sentences.append(
                _claim(
                    f"Mitigation starts with the runbook section {section['section']}.",
                    [section],
                )
            )
    return sentences


def _impact(claims: list[dict]) -> list[dict]:
    baseline = _bounds(claims[1])
    onset = _bounds(claims[0])
    if baseline is None or onset is None:
        raise ValueError("forensics claims do not cite a span start and end")
    sentences = [
        _claim(
            (
                f"Span {baseline['span_id']} ran from {baseline['start']} to {baseline['end']} "
                f"({baseline['duration']}ms), and span {onset['span_id']} ran from {onset['start']} "
                f"to {onset['end']} ({onset['duration']}ms)."
            ),
            [baseline["start_cite"], baseline["end_cite"], onset["start_cite"], onset["end_cite"]],
        )
    ]
    for claim in claims:
        log = _require_log(claim)
        copied = _copy_telemetry(log)
        body = _body(claim.get("text") or "")
        if body is None:
            text = (
                f"The log at {copied['timestamp_unix_nano']} on span {copied['span_id']} "
                f"is in trace {copied['trace_id']}."
            )
        else:
            text = (
                f"The log at {copied['timestamp_unix_nano']} on span {copied['span_id']} says {body!r}."
            )
        sentences.append(_claim(text, [copied]))
    return sentences


def _timeline(claims: list[dict]) -> list[dict]:
    events = []
    for index, claim in enumerate(claims):
        log = _copy_telemetry(_require_log(claim))
        if index == 0:
            root = _root_span(claim, log["span_id"])
            if root is not None:
                copied = _copy_telemetry(root)
                events.append(
                    (
                        copied["timestamp_unix_nano"],
                        f"Trace {copied['trace_id']} starts at {copied['timestamp_unix_nano']} on span {copied['span_id']}.",
                        [copied],
                    )
                )
        events.append(
            (
                log["timestamp_unix_nano"],
                f"The log on span {log['span_id']} is at {log['timestamp_unix_nano']}.",
                [log],
            )
        )
    events.sort(key=lambda item: (item[0], item[1]))
    return [_claim(text, citations) for _, text, citations in events]


def _root_cause(archaeology: dict, onset_log: dict) -> list[dict]:
    lead = _first_code(archaeology)
    if lead is None:
        log = _copy_telemetry(onset_log)
        return [
            _claim(
                (
                    f"No cited commit explains trace {log['trace_id']} "
                    f"at log timestamp {log['timestamp_unix_nano']}."
                ),
                [log],
            )
        ]
    code = _copy_code(lead)
    sentences = [
        _claim(
            f"Commit {code['commit']} sets `{code['text']}` at {code['file']}:{code['line']}.",
            [code],
        )
    ]
    parent = _other_code(archaeology, code["commit"])
    if parent is not None:
        copied = _copy_code(parent)
        sentences.append(
            _claim(
                f"Commit {copied['commit']} sets `{copied['text']}` at {copied['file']}:{copied['line']}.",
                [copied],
            )
        )
    return sentences


def _evidence(claims: list[dict], archaeology: dict) -> list[dict]:
    sentences = [_forensics_sentence(claim) for claim in claims]
    for claim in _claim_list(archaeology, "archaeologist"):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict) and citation.get("commit"):
                sentences.append(_code_sentence(citation))
    if not sentences:
        raise ValueError("upstream reports have no evidence claims")
    return sentences


def _forensics_sentence(claim: dict) -> dict:
    log = _copy_telemetry(_require_log(claim))
    body = _body(claim.get("text") or "")
    parts = []
    citations = []
    seen = set()
    root = _root_span(claim, log["span_id"])
    if root is not None:
        copied = _copy_telemetry(root)
        parts.append(
            f"trace {copied['trace_id']} starts at {copied['timestamp_unix_nano']} on span {copied['span_id']}"
        )
        _add(citations, seen, copied)
    bounds = _bounds(claim)
    if bounds is not None:
        parts.append(f"span {bounds['span_id']} runs from {bounds['start']} to {bounds['end']}")
        _add(citations, seen, bounds["start_cite"])
        _add(citations, seen, bounds["end_cite"])
    said = f" says {body!r}" if body else ""
    parts.append(f"the log at {log['timestamp_unix_nano']} on span {log['span_id']}{said}")
    _add(citations, seen, log)
    for citation in claim.get("citations") or []:
        if not isinstance(citation, dict) or citation.get("file") not in _TELEMETRY:
            continue
        copied = _copy_telemetry(citation)
        if _telemetry_key(copied) in seen:
            continue
        parts.append(f"span {copied['span_id']} is at {copied['timestamp_unix_nano']}")
        _add(citations, seen, copied)
    text = "; ".join(parts)
    return _claim(text[0].upper() + text[1:] + ".", citations)


def _code_sentence(citation: dict) -> dict:
    code = _copy_code(citation)
    return _claim(
        f"Commit {code['commit']} at {code['file']}:{code['line']} reads `{code['text']}`.",
        [code],
    )


def _mitigation(forensics: dict, archaeology: dict, runbook: dict, onset_log: dict) -> list[dict]:
    if not runbook.get("matched"):
        return [_unmatched(archaeology, onset_log)]
    steps = runbook.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("matched runbook report has no steps")
    return [_step_sentence(step, forensics, archaeology) for step in steps]


def _unmatched(archaeology: dict, onset_log: dict) -> dict:
    log = _copy_telemetry(onset_log)
    lead = _first_code(archaeology)
    if lead is None:
        return _claim(
            (
                f"No runbook section matched trace {log['trace_id']} "
                f"at log timestamp {log['timestamp_unix_nano']}."
            ),
            [log],
        )
    code = _copy_code(lead)
    return _claim(
        (
            f"No runbook section matched commit {code['commit']} at {code['file']}:{code['line']}, "
            f"and the onset log is at {log['timestamp_unix_nano']}."
        ),
        [code, log],
    )


def _step_sentence(step: dict, forensics: dict, archaeology: dict) -> dict:
    if not isinstance(step, dict):
        raise ValueError("runbook step is not an object")
    citations = step.get("citations")
    if not isinstance(citations, list):
        raise ValueError("runbook step has no citations")
    section = None
    logs = []
    commits = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        if citation.get("type") == "runbook" and section is None:
            section = {"file": citation.get("file"), "section": citation.get("section")}
            if not isinstance(section["file"], str) or not isinstance(section["section"], str):
                raise ValueError("runbook citation has no section")
        elif citation.get("type") == "forensics":
            logs.append(_find_log(forensics, citation.get("timestamp_unix_nano")))
        elif citation.get("type") == "archaeologist":
            commits.append(_find_code(archaeology, citation.get("commit")))
    if section is None:
        raise ValueError("runbook step has no section citation")
    cited = [f"log timestamp {log['timestamp_unix_nano']}" for log in logs]
    cited += [f"commit {code['commit']}" for code in commits]
    if not cited:
        text = f"Runbook section {section['section']} applies."
    elif len(cited) == 1:
        text = f"Runbook section {section['section']} cites {cited[0]}."
    else:
        text = f"Runbook section {section['section']} cites {', '.join(cited[:-1])}, and {cited[-1]}."
    return _claim(text, [section, *logs, *commits])


def _first_runbook_citation(runbook: dict) -> dict | None:
    steps = runbook.get("steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, dict):
            continue
        for citation in step.get("citations") or []:
            if isinstance(citation, dict) and citation.get("type") == "runbook":
                return {"file": citation["file"], "section": citation["section"]}
    return None


def _bounds(claim: dict) -> dict | None:
    log = _log(claim)
    if log is None:
        return None
    spans = [
        citation
        for citation in claim.get("citations") or []
        if isinstance(citation, dict)
        and citation.get("file") == "traces.jsonl"
        and citation.get("span_id") == log["span_id"]
    ]
    if len(spans) < 2:
        return None
    start = min(spans, key=lambda citation: citation["timestamp_unix_nano"])
    end = max(spans, key=lambda citation: citation["timestamp_unix_nano"])
    duration = (int(end["timestamp_unix_nano"]) - int(start["timestamp_unix_nano"])) // 1_000_000
    return {
        "span_id": log["span_id"],
        "start": int(start["timestamp_unix_nano"]),
        "end": int(end["timestamp_unix_nano"]),
        "duration": duration,
        "start_cite": _copy_telemetry(start),
        "end_cite": _copy_telemetry(end),
    }


def _root_span(claim: dict, span_id: str) -> dict | None:
    for citation in claim.get("citations") or []:
        if (
            isinstance(citation, dict)
            and citation.get("file") == "traces.jsonl"
            and citation.get("span_id") != span_id
        ):
            return citation
    return None


def _find_log(forensics: dict, timestamp) -> dict:
    for claim in _claim_list(forensics, "forensics"):
        for citation in claim.get("citations") or []:
            if (
                isinstance(citation, dict)
                and citation.get("file") == "logs.jsonl"
                and citation.get("timestamp_unix_nano") == timestamp
            ):
                return _copy_telemetry(citation)
    raise ValueError(f"forensics report has no log at {timestamp}")


def _find_code(archaeology: dict, commit) -> dict:
    for claim in _claim_list(archaeology, "archaeologist"):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict) and citation.get("commit") == commit:
                return _copy_code(citation)
    raise ValueError(f"archaeologist report does not cite {commit}")


def _first_code(archaeology: dict) -> dict | None:
    for claim in _claim_list(archaeology, "archaeologist"):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict) and citation.get("commit"):
                return citation
    return None


def _other_code(archaeology: dict, commit: str) -> dict | None:
    for claim in _claim_list(archaeology, "archaeologist"):
        for citation in claim.get("citations") or []:
            if isinstance(citation, dict) and citation.get("commit") and citation["commit"] != commit:
                return citation
    return None


def _commit(archaeology: dict):
    commit = archaeology.get("commit")
    if commit is None:
        return None
    if not isinstance(commit, str):
        raise ValueError("archaeologist commit is not a string")
    return commit


def _service_kind(forensics: dict) -> tuple[str, str]:
    service = forensics.get("service")
    kind = forensics.get("kind")
    if not isinstance(service, str) or not service:
        raise ValueError("forensics report has no service")
    if not isinstance(kind, str) or not kind:
        raise ValueError("forensics report has no kind")
    return service, kind


def _claim_list(report: dict, label: str) -> list[dict]:
    claims = report.get("claims")
    if not isinstance(claims, list):
        raise ValueError(f"{label} report claims are not a list")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError(f"{label} claim is not an object")
    return claims


def _require_log(claim: dict) -> dict:
    found = _log(claim)
    if found is None:
        raise ValueError("forensics claim has no log citation")
    return found


def _log(claim: dict) -> dict | None:
    for citation in claim.get("citations") or []:
        if isinstance(citation, dict) and citation.get("file") == "logs.jsonl":
            return citation
    return None


def _body(text: str) -> str | None:
    match = _BODY.search(text)
    if match is None:
        return None
    return match.group(1)


def _copy_telemetry(citation: dict) -> dict:
    filename = citation.get("file")
    if filename not in _TELEMETRY:
        raise ValueError("forensics citation is not a trace or log line")
    line = citation.get("line")
    timestamp = citation.get("timestamp_unix_nano")
    trace_id = citation.get("trace_id")
    span_id = citation.get("span_id")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError("forensics citation line is not a positive integer")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        raise ValueError("forensics citation timestamp is not an integer")
    if not isinstance(trace_id, str) or not trace_id:
        raise ValueError("forensics citation has no trace_id")
    if not isinstance(span_id, str) or not span_id:
        raise ValueError("forensics citation has no span_id")
    return {
        "file": filename,
        "line": line,
        "span_id": span_id,
        "timestamp_unix_nano": timestamp,
        "trace_id": trace_id,
    }


def _copy_code(citation: dict) -> dict:
    commit = citation.get("commit")
    path = citation.get("file")
    line = citation.get("line")
    text = citation.get("text")
    if not isinstance(commit, str) or not commit:
        raise ValueError("archaeologist citation has no commit")
    if not isinstance(path, str) or not path:
        raise ValueError("archaeologist citation has no file")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError("archaeologist citation line is not a positive integer")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("archaeologist citation has no line text")
    return {"commit": commit, "file": path, "line": line, "text": text.strip()}


def _add(citations: list[dict], seen: set, citation: dict) -> None:
    key = _telemetry_key(citation)
    if key in seen:
        return
    seen.add(key)
    citations.append(citation)


def _telemetry_key(citation: dict) -> tuple:
    return (
        citation.get("file"),
        citation.get("line"),
        citation.get("timestamp_unix_nano"),
        citation.get("span_id"),
        citation.get("trace_id"),
    )


def _claim(text: str, citations: list[dict]) -> dict:
    if not text.endswith("."):
        text += "."
    return {"text": text, "citations": citations}
