"""Reject a report sentence that does not cite a resolvable source.

A log citation matches that line of traces.jsonl or logs.jsonl. A commit
citation is a commit in the history, and the file and line match when the
citation names them. A runbook citation is a heading in that file. A
sentence that names an id its citations do not carry does not resolve.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from code_archaeologist.history import file_at, is_commit
from runbook.books import default_directory

_SECTIONS = ("summary", "impact", "timeline", "root_cause", "evidence", "mitigation")
_TELEMETRY = {"logs.jsonl", "traces.jsonl"}
_HASH = re.compile(r"^[0-9a-f]{40}$")
_HEX = re.compile(r"\b[0-9a-f]{40}\b|\b[0-9a-f]{32}\b|\b[0-9a-f]{16}\b")
_TIMESTAMP = re.compile(r"\b\d{16,}\b")
_LINE = re.compile(r"\b(?:gateway|orders|inventory|payments)\.py:\d+\b")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_QUIET = "No error-rate or latency spike found."


def check_report(
    report: dict,
    directory: Path | str,
    repo: Path | str,
    runbooks: Path | str | None = None,
) -> list[str]:
    """Return one problem string per claim or citation that does not resolve."""
    if not isinstance(report, dict):
        return ["report is not an object"]
    sections = report.get("sections")
    if not isinstance(sections, dict):
        return ["report sections are not an object"]
    problems = []
    for name in _SECTIONS:
        if name not in sections:
            problems.append(f"report is missing {name}")
    incident = report.get("incident")
    if not isinstance(incident, bool):
        return problems + ["report incident is not a boolean"]
    if problems:
        return problems
    directory = Path(directory)
    repo = Path(repo)
    books = default_directory() if runbooks is None else Path(runbooks)
    if not incident:
        return _quiet(sections, directory, repo, books)
    for name in _SECTIONS:
        claims = sections.get(name)
        if not isinstance(claims, list) or not claims:
            problems.append(f"{name} has no claims")
            continue
        for index, claim in enumerate(claims):
            problems.extend(_claim(directory, repo, books, name, index, claim))
    return problems


def _quiet(sections: dict, directory: Path, repo: Path, books: Path) -> list[str]:
    summary = sections.get("summary")
    if not isinstance(summary, list) or len(summary) != 1 or not isinstance(summary[0], dict):
        return ["quiet report summary is not one sentence"]
    text = summary[0].get("text")
    if not isinstance(text, str) or not text.strip():
        return ["quiet report summary has no text"]
    problems = []
    citations = summary[0].get("citations")
    if citations:
        problems.extend(_claim(directory, repo, books, "summary", 0, summary[0]))
    elif text.strip() != _QUIET:
        problems.append("quiet report summary has no citation")
    for name in _SECTIONS:
        if name == "summary":
            continue
        claims = sections.get(name)
        if isinstance(claims, list) and claims:
            problems.append(f"quiet report has claims in {name}")
    return problems


def _claim(directory: Path, repo: Path, books: Path, section: str, index: int, claim) -> list[str]:
    if not isinstance(claim, dict):
        return [f"{section} claim {index} does not resolve: claim is not an object"]
    text = claim.get("text")
    if not isinstance(text, str) or not text.strip():
        return [f"{section} claim {index} does not resolve: claim has no text"]
    citations = claim.get("citations")
    if not isinstance(citations, list) or not citations:
        return [f"{section} claim {index} does not resolve: claim has no citation"]
    problems = []
    for sentence_index, sentence in enumerate(_sentences(text)):
        if not any(isinstance(citation, dict) and _mentions(sentence, citation) for citation in citations):
            problems.append(
                f"{section} claim {index} sentence {sentence_index} does not resolve: sentence has no citation"
            )
    for citation in citations:
        problem = _resolve(directory, repo, books, citation)
        if problem:
            problems.append(f"{section} claim {index} does not resolve: {problem}")
            continue
        if isinstance(citation, dict) and not _mentions(text, citation):
            problems.append(f"{section} claim {index} does not resolve: sentence does not link to the citation")
    extra = _extra_ids(text, citations)
    for item in extra:
        problems.append(f"{section} claim {index} does not resolve: sentence names {item} and it is not cited")
    return problems


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE.split(text.strip()) if part.strip()]
    return parts or [text.strip()]


def _mentions(text: str, citation: dict) -> bool:
    kind = _kind(citation)
    if kind == "runbook":
        section = citation.get("section")
        return isinstance(section, str) and bool(section) and section in text
    return bool(_anchors(citation) & _mentioned(text))


def _extra_ids(text: str, citations: list) -> list[str]:
    allowed = set()
    for citation in citations:
        if isinstance(citation, dict):
            allowed |= _anchors(citation)
    extra = sorted(_mentioned(text) - allowed)
    return [f"{kind} {value}" for kind, value in extra]


def _mentioned(text: str) -> set[tuple[str, str]]:
    found = set()
    covered = []
    for match in _HEX.finditer(text):
        token = match.group(0)
        covered.append(match.span())
        if len(token) == 40:
            found.add(("commit", token))
        elif len(token) == 32:
            found.add(("trace", token))
        else:
            found.add(("span", token))
    for match in _TIMESTAMP.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        found.add(("timestamp", match.group(0)))
    for match in _LINE.finditer(text):
        found.add(("line", match.group(0)))
    return found


def _anchors(citation: dict) -> set[tuple[str, str]]:
    kind = _kind(citation)
    found = set()
    if kind == "telemetry":
        timestamp = citation.get("timestamp_unix_nano")
        if isinstance(timestamp, int) and not isinstance(timestamp, bool):
            found.add(("timestamp", str(timestamp)))
        trace_id = citation.get("trace_id")
        span_id = citation.get("span_id")
        if isinstance(trace_id, str) and trace_id:
            found.add(("trace", trace_id))
        if isinstance(span_id, str) and span_id:
            found.add(("span", span_id))
    elif kind == "code":
        commit = citation.get("commit")
        if isinstance(commit, str):
            found.add(("commit", commit))
        path = citation.get("file")
        line = citation.get("line")
        if isinstance(path, str) and isinstance(line, int) and not isinstance(line, bool):
            found.add(("line", f"{path}:{line}"))
    return found


def _resolve(directory: Path, repo: Path, books: Path, citation) -> str | None:
    kind = _kind(citation)
    if kind == "telemetry":
        return _telemetry(directory, citation)
    if kind == "code":
        return _code(repo, citation)
    if kind == "runbook":
        return _runbook(books, citation)
    return "citation is not a log timestamp, trace or span, commit, file line, or runbook section"


def _kind(citation) -> str | None:
    if not isinstance(citation, dict):
        return None
    has_section = "section" in citation
    has_commit = "commit" in citation
    has_telemetry = citation.get("file") in _TELEMETRY
    if sum((has_section, has_commit, has_telemetry)) != 1:
        return None
    if has_section:
        return "runbook"
    if has_commit:
        return "code"
    return "telemetry"


def _telemetry(directory: Path, citation: dict) -> str | None:
    filename = citation.get("file")
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


def _code(repo: Path, citation: dict) -> str | None:
    sha = citation.get("commit")
    if not isinstance(sha, str) or not _HASH.fullmatch(sha):
        return "citation commit is not a full hash"
    if not is_commit(repo, sha):
        return f"commit {sha} is not in the history"
    path = citation.get("file")
    line = citation.get("line")
    if path is None and line is None:
        return None
    path_problem = _bad_path(path)
    if path_problem:
        return path_problem
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return "citation line is not a positive integer"
    text = file_at(repo, sha, path)
    if text is None:
        return f"{path} is not in {sha}"
    lines = text.splitlines()
    if line > len(lines):
        return f"{path}:{line} is past the end of the file at {sha}"
    expected = citation.get("text")
    if not isinstance(expected, str) or not expected.strip():
        return "citation has no line text"
    if lines[line - 1].strip() != expected.strip():
        return f"{path}:{line} text does not match"
    return None


def _runbook(books: Path, citation: dict) -> str | None:
    filename = citation.get("file")
    section = citation.get("section")
    if not isinstance(filename, str) or "/" in filename or "\\" in filename or not filename.endswith(".md"):
        return "runbook file is not a markdown file in the catalog"
    if not isinstance(section, str) or not section.strip():
        return "runbook section is empty"
    path = books / filename
    if not path.is_file():
        return f"{filename} is not in the runbook catalog"
    headings = re.findall(r"^## (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if section not in headings:
        return f"section {section!r} is not in {filename}"
    return None


def _bad_path(path) -> str | None:
    if not isinstance(path, str) or not path or path.startswith("/") or path.startswith("\\"):
        return "citation file is not a path in the commit"
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return "citation file is not a path in the commit"
    return None
