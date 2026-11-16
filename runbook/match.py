"""Pick the runbook whose kind and line shape match the upstream reports.

The fault name is not an input. Two payments error-rate incidents need
different procedures: an inverted `if` rolls back, and a changed constant
is reverted in place. The cited line is what distinguishes them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from runbook.books import Runbook, StepTemplate
from runbook.load import Case

_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*) = (\d+)$")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class _Missing(Exception):
    """A placeholder was in the step, and the upstream reports have no value for it."""


@dataclass(frozen=True)
class Choice:
    book: Runbook | None
    steps: tuple[dict, ...]
    reason: str


def select(case: Case, books: list[Runbook]) -> Choice:
    found = [book for book in books if book.kind == case.kind and book.line == case.line_shape]
    if not found:
        shown = case.line_text or "absent"
        return Choice(None, (), f"The cited line is {shown!r} ({case.line_shape}).")
    if len(found) > 1:
        names = ", ".join(sorted(book.id for book in found))
        raise ValueError(f"more than one runbook matches: {names}")
    book = found[0]
    steps = _steps(case, book)
    if steps is None:
        return Choice(
            None,
            (),
            (
                f"{book.id} matches this {case.kind} {case.line_shape} line, "
                "but the upstream reports do not cite enough evidence to fill the steps."
            ),
        )
    return Choice(book, tuple(steps), "")


def _steps(case: Case, book: Runbook) -> list[dict] | None:
    built = []
    for index, template in enumerate(book.steps, start=1):
        if not _ready(case, template):
            return None
        target = _target(case, template)
        if target is None:
            return None
        try:
            text = _fill(template.text, _values(case, template, target))
        except _Missing:
            return None
        built.append(
            {
                "order": index,
                "action": template.action,
                "section": template.section,
                "text": text,
                "target": target,
                "citations": _citations(case, book, template),
            }
        )
    return built


def _ready(case: Case, template: StepTemplate) -> bool:
    if _target(case, template) is None:
        return False
    if case.onset_claim is None or case.onset_timestamp is None:
        return False
    if template.action == "shed_load":
        return True
    if case.commit_claim is None:
        return False
    if template.action in {"rollback", "revert_config"} and case.parent_claim is None:
        return False
    if template.action == "raise_timeout" and template.param("file"):
        if case.timeout_claim is None or case.timeout_timestamp is None:
            return False
    return True


def _target(case: Case, template: StepTemplate) -> dict | None:
    if template.action == "rollback":
        if not (case.commit and case.parent and case.file):
            return None
        return {"commit": case.commit, "parent": case.parent, "file": case.file}
    if template.action == "revert_config":
        name, _current = _assignment(case.line_text)
        parent_name, parent_value = _assignment(case.parent_text)
        if not (case.commit and case.parent and case.file and name and name == parent_name):
            return None
        if parent_value is None:
            return None
        return {
            "commit": case.commit,
            "parent": case.parent,
            "file": case.file,
            "constant": name,
            "value": parent_value,
        }
    if template.action == "raise_timeout":
        constant = template.param("constant") or _assignment(case.line_text)[0]
        path = template.param("file") or case.file
        value = _timeout_value(case)
        if not (constant and path and case.commit and value is not None):
            return None
        return {"commit": case.commit, "file": path, "constant": constant, "value": value}
    if template.action == "shed_load":
        if not case.service:
            return None
        return {"service": case.service}
    raise ValueError(f"unknown action {template.action}")


def _citations(case: Case, book: Runbook, template: StepTemplate) -> list[dict]:
    cites = [{"type": "runbook", "file": book.path.name, "section": template.section}]
    if template.action == "raise_timeout" and template.param("file"):
        cites.append(
            {
                "type": "forensics",
                "claim": case.timeout_claim,
                "timestamp_unix_nano": case.timeout_timestamp,
            }
        )
    else:
        cites.append(
            {
                "type": "forensics",
                "claim": case.onset_claim,
                "timestamp_unix_nano": case.onset_timestamp,
            }
        )
    if template.action != "shed_load":
        cites.append({"type": "archaeologist", "claim": case.commit_claim, "commit": case.commit})
    if template.action in {"rollback", "revert_config"}:
        cites.append({"type": "archaeologist", "claim": case.parent_claim, "commit": case.parent})
    return cites


def _values(case: Case, template: StepTemplate, target: dict) -> dict:
    restored = target.get("value") if template.action == "revert_config" else None
    raised = target.get("value") if template.action == "raise_timeout" else None
    return {
        "baseline_ms": _num(case.baseline_ms),
        "caller_constant": template.param("constant"),
        "caller_file": template.param("file"),
        "commit": case.commit,
        "constant": target.get("constant"),
        "file": target.get("file") or case.file,
        "incident_ms": _num(case.incident_ms),
        "kind": case.kind,
        "line": case.line,
        "line_text": case.line_text,
        "parent": case.parent,
        "parent_text": case.parent_text,
        "service": case.service,
        "signature": case.signature,
        "timeout_ms": case.timeout_ms,
        "timeout_timestamp": case.timeout_timestamp,
        "timeout_value": raised,
        "timestamp": case.onset_timestamp,
        "value": restored,
    }


def _fill(template: str, values: dict) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"unknown placeholder {{{key}}}")
        if values[key] is None:
            raise _Missing(key)
        return str(values[key])

    return " ".join(_PLACEHOLDER.sub(replace, template).split())


def _assignment(text: str | None) -> tuple[str | None, int | None]:
    if not text:
        return None, None
    match = _ASSIGN.fullmatch(text)
    if match is None:
        return None, None
    return match.group(1), int(match.group(2))


def _timeout_value(case: Case) -> int | None:
    """The caller should wait at least as long as the dependency took."""
    if case.incident_ms is None:
        return None
    value = int(case.incident_ms)
    if case.timeout_ms is not None and value <= case.timeout_ms:
        value = case.timeout_ms + 1
    return value


def _num(value: float | None) -> str | None:
    if value is None:
        return None
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"
