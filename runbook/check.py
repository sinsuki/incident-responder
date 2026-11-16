"""Every step must cite a real runbook section and a real upstream claim.

A runbook citation names a heading in the selected file. An evidence
citation names a forensics claim that contains that log timestamp, or an
archaeologist claim that contains that commit. Rollback and config revert
have to cite both the implicated commit and the parent they deploy.
"""

from __future__ import annotations

import re
from pathlib import Path

from runbook.books import default_directory, load_runbooks

_HASH = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_FILES = {"gateway.py", "orders.py", "inventory.py", "payments.py"}


def check_citations(
    report: dict,
    forensics: dict,
    archaeology: dict,
    runbooks: Path | str | None = None,
) -> list[str]:
    """Return one problem string per step or citation that does not resolve."""
    problems = _shape(report)
    if problems or not report["matched"]:
        return problems
    directory = default_directory() if runbooks is None else Path(runbooks)
    try:
        catalog = {book.id: book for book in load_runbooks(directory)}
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]
    book = catalog.get(report.get("runbook"))
    if book is None:
        return [f"runbook {report.get('runbook')!r} is not in the catalog"]
    if book.path.name != report.get("runbook_file"):
        return ["runbook file does not match the catalog"]
    if len(report["steps"]) != len(book.steps):
        problems.append(f"report has {len(report['steps'])} steps and {book.id} has {len(book.steps)}")
    sections = {item.section for item in book.steps}
    for index, step in enumerate(report["steps"]):
        expected = book.steps[index] if index < len(book.steps) else None
        problems.extend(
            _step(index, step, expected, book.path.name, sections, report, forensics, archaeology)
        )
    return problems


def _shape(report) -> list[str]:
    if not isinstance(report, dict):
        return ["report is not an object"]
    if not isinstance(report.get("matched"), bool):
        return ["report matched is not a boolean"]
    steps = report.get("steps")
    if not isinstance(steps, list):
        return ["report steps are not a list"]
    if not report["matched"]:
        if report.get("runbook") is not None or report.get("runbook_file") is not None:
            return ["unmatched report names a runbook"]
        if steps:
            return ["unmatched report has steps"]
        return []
    if not isinstance(report.get("runbook"), str) or not report["runbook"]:
        return ["matched report names no runbook"]
    if not isinstance(report.get("runbook_file"), str) or not report["runbook_file"]:
        return ["matched report names no runbook file"]
    if not steps:
        return ["matched report has no steps"]
    return []


def _step(index, step, expected, filename, sections, report, forensics, archaeology) -> list[str]:
    if not isinstance(step, dict):
        return [f"step {index} does not resolve: step is not an object"]
    problems = []
    if step.get("order") != index + 1:
        problems.append(f"step {index} does not resolve: step order is {step.get('order')!r}")
    if expected is None:
        problems.append(f"step {index} does not resolve: step is not in the runbook")
        return problems
    if step.get("action") != expected.action:
        problems.append(f"step {index} does not resolve: action does not match the runbook")
    if step.get("section") != expected.section:
        problems.append(f"step {index} does not resolve: section does not match the runbook")
    if not isinstance(step.get("text"), str) or not step["text"].strip():
        problems.append(f"step {index} does not resolve: step has no text")
    citations = step.get("citations")
    if not isinstance(citations, list) or not citations:
        problems.append(f"step {index} does not resolve: step has no citations")
        return problems
    saw_runbook = False
    saw_evidence = False
    cited_commits = set()
    for citation in citations:
        problem, kind, commit = _resolve(citation, expected, filename, sections, forensics, archaeology)
        if problem:
            problems.append(f"step {index} does not resolve: {problem}")
            continue
        if kind == "runbook":
            saw_runbook = True
        else:
            saw_evidence = True
        if commit:
            cited_commits.add(commit)
    if not saw_runbook:
        problems.append(f"step {index} does not resolve: step has no runbook citation")
    if not saw_evidence:
        problems.append(f"step {index} does not resolve: step has no evidence citation")
    problems.extend(_target(index, step, report, cited_commits))
    return problems


def _resolve(citation, expected, filename, sections, forensics, archaeology):
    if not isinstance(citation, dict):
        return "citation is not an object", None, None
    kind = citation.get("type")
    if kind == "runbook":
        return _runbook(citation, expected, filename, sections), "runbook", None
    if kind == "forensics":
        return _timestamp(citation, forensics), "forensics", None
    if kind == "archaeologist":
        problem, commit = _commit_citation(citation, archaeology)
        return problem, "archaeologist", commit
    return "citation type is not a runbook section or upstream evidence", None, None


def _runbook(citation, expected, filename: str, sections: set[str]) -> str | None:
    if citation.get("file") != filename:
        return "runbook file does not match the selected runbook"
    section = citation.get("section")
    if not isinstance(section, str) or section not in sections:
        return f"section {section!r} is not in {filename}"
    if section != expected.section:
        return "runbook section does not match this step"
    return None


def _timestamp(citation: dict, report: dict) -> str | None:
    claims = _upstream_claims(report, "forensics")
    if isinstance(claims, str):
        return claims
    problem = _index(citation.get("claim"), len(claims))
    if problem:
        return problem
    timestamp = citation.get("timestamp_unix_nano")
    if isinstance(timestamp, bool) or not isinstance(timestamp, int):
        return "timestamp is not an integer"
    if not _has(claims[citation["claim"]], "timestamp_unix_nano", timestamp):
        return "timestamp is not in that forensics claim"
    return None


def _commit_citation(citation: dict, report: dict):
    claims = _upstream_claims(report, "archaeologist")
    if isinstance(claims, str):
        return claims, None
    problem = _index(citation.get("claim"), len(claims))
    if problem:
        return problem, None
    commit = citation.get("commit")
    if not isinstance(commit, str) or not _HASH.fullmatch(commit):
        return "citation commit is not a full hash", None
    if not _has(claims[citation["claim"]], "commit", commit):
        return "commit is not in that archaeologist claim", None
    return None, commit


def _target(index: int, step: dict, report: dict, cited_commits: set[str]) -> list[str]:
    action = step.get("action")
    target = step.get("target")
    if not isinstance(target, dict):
        return [f"step {index} does not resolve: step has no target"]
    if action == "shed_load":
        if target.get("service") != report.get("service"):
            return [f"step {index} does not resolve: shed load service does not match the report"]
        return []
    problems = []
    if target.get("file") not in _FILES:
        problems.append(f"step {index} does not resolve: target file is not a service module")
    commit = target.get("commit")
    if not isinstance(commit, str) or not _HASH.fullmatch(commit):
        problems.append(f"step {index} does not resolve: target commit is not a full hash")
    elif commit not in cited_commits:
        problems.append(f"step {index} does not resolve: implicated commit is not cited")
    if action in {"rollback", "revert_config"}:
        parent = target.get("parent")
        if not isinstance(parent, str) or not _HASH.fullmatch(parent):
            problems.append(f"step {index} does not resolve: target parent is not a full hash")
        elif parent not in cited_commits:
            problems.append(f"step {index} does not resolve: parent commit is not cited")
    if action in {"revert_config", "raise_timeout"}:
        constant = target.get("constant")
        if not isinstance(constant, str) or not _NAME.fullmatch(constant):
            problems.append(f"step {index} does not resolve: target constant is not a name")
        value = target.get("value")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(f"step {index} does not resolve: target value is not a whole number")
    return problems


def _upstream_claims(report: dict, label: str):
    if not isinstance(report, dict):
        return f"{label} report is not an object"
    claims = report.get("claims")
    if not isinstance(claims, list):
        return f"{label} report claims are not a list"
    return claims


def _index(index, length: int) -> str | None:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < length:
        return "claim is out of range"
    return None


def _has(claim, key: str, value) -> bool:
    if not isinstance(claim, dict):
        return False
    citations = claim.get("citations")
    if not isinstance(citations, list):
        return False
    return any(isinstance(item, dict) and item.get(key) == value for item in citations)
