"""Turn a matched runbook into the JSON report a later agent can read."""

from __future__ import annotations

from runbook.books import Runbook
from runbook.load import Case


def no_incident() -> dict:
    return _envelope(
        incident=False,
        matched=False,
        service=None,
        kind=None,
        started=None,
        commit=None,
        runbook=None,
        runbook_file=None,
        summary="No incident to mitigate.",
        steps=[],
    )


def no_match(case: Case, reason: str) -> dict:
    return _envelope(
        incident=True,
        matched=False,
        service=case.service,
        kind=case.kind,
        started=case.started_at_unix_nano,
        commit=case.commit,
        runbook=None,
        runbook_file=None,
        summary=f"No runbook matches this {case.service} {case.kind}. {reason}",
        steps=[],
    )


def build_report(case: Case, book: Runbook, steps: tuple[dict, ...] | list[dict]) -> dict:
    commit = f" Commit {case.commit}." if case.commit else ""
    summary = (
        f"{book.title} ({book.id}) matches this {case.service} {case.kind}.{commit} "
        f"The steps are {_actions(steps)}. "
        f"The onset log is at {case.onset_timestamp}."
    )
    return _envelope(
        incident=True,
        matched=True,
        service=case.service,
        kind=case.kind,
        started=case.started_at_unix_nano,
        commit=case.commit,
        runbook=book.id,
        runbook_file=book.path.name,
        summary=summary,
        steps=list(steps),
    )


def _actions(steps) -> str:
    names = [step["action"] for step in steps]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", then " + names[-1]


def _envelope(**fields) -> dict:
    return {
        "schema_version": 1,
        "incident": fields["incident"],
        "matched": fields["matched"],
        "service": fields["service"],
        "kind": fields["kind"],
        "started_at_unix_nano": fields["started"],
        "commit": fields["commit"],
        "runbook": fields["runbook"],
        "runbook_file": fields["runbook_file"],
        "summary": fields["summary"],
        "steps": fields["steps"],
        "tokens": {"input": 0, "output": 0},
    }
