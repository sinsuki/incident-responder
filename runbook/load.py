"""Read the two upstream reports into the fields matching may use.

ground_truth.json is not a field here. Fault names and commit subjects are
not read. Extra keys on either report are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from code_archaeologist.load import read_profile

_HASH = re.compile(r"^[0-9a-f]{40}$")
_TIMEOUT_CONST = re.compile(r"^[A-Z][A-Z0-9_]*_TIMEOUT_MS = \d+$")
_DURATION = re.compile(r"^[A-Z][A-Z0-9_]*_MS = \d+$")
_CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]* = \d+$")
_FILES = {"gateway.py", "orders.py", "inventory.py", "payments.py"}


@dataclass(frozen=True)
class Case:
    incident: bool
    service: str | None
    kind: str | None
    started_at_unix_nano: int | None
    baseline_ms: float | None
    incident_ms: float | None
    signature: str | None
    timeout_ms: int | None
    commit: str | None
    parent: str | None
    file: str | None
    line: int | None
    line_text: str | None
    parent_text: str | None
    line_shape: str
    onset_claim: int | None
    onset_timestamp: int | None
    timeout_claim: int | None
    timeout_timestamp: int | None
    commit_claim: int | None
    parent_claim: int | None


def read_case(forensics: dict, archaeology: dict) -> Case:
    if not isinstance(archaeology, dict):
        raise ValueError("archaeologist report is not an object")
    profile = read_profile(forensics)
    if not profile.incident:
        return _quiet()
    _agree(profile.service, archaeology.get("service"), "service")
    _agree(profile.kind, archaeology.get("kind"), "kind")
    forensics_claims = _claims(forensics, "forensics")
    archaeology_claims = _claims(archaeology, "archaeologist")
    onset_claim, onset_timestamp = _first_log(forensics_claims)
    timeout_claim, timeout_timestamp = _timeout_log(forensics_claims)
    commit, ranked = _commit(archaeology)
    parent, parent_claim, parent_text, commit_claim = _parents(archaeology_claims, commit)
    path, line, line_text = _line(ranked, commit)
    return Case(
        incident=True,
        service=profile.service,
        kind=profile.kind,
        started_at_unix_nano=profile.started_at_unix_nano,
        baseline_ms=profile.baseline_ms,
        incident_ms=profile.incident_ms,
        signature=profile.signature,
        timeout_ms=profile.timeout_ms,
        commit=commit,
        parent=parent,
        file=path,
        line=line,
        line_text=line_text,
        parent_text=parent_text,
        line_shape=_shape(line_text, commit),
        onset_claim=onset_claim,
        onset_timestamp=onset_timestamp,
        timeout_claim=timeout_claim,
        timeout_timestamp=timeout_timestamp,
        commit_claim=commit_claim,
        parent_claim=parent_claim,
    )


def _quiet() -> Case:
    return Case(
        False, None, None, None, None, None, None, None, None, None, None, None, None, None,
        "none", None, None, None, None, None, None,
    )


def _agree(expected: str | None, actual, label: str) -> None:
    if actual is not None and actual != expected:
        raise ValueError(f"archaeologist {label} does not match the forensics report")


def _claims(report: dict, label: str) -> list[dict]:
    claims = report.get("claims")
    if not isinstance(claims, list):
        raise ValueError(f"{label} report claims are not a list")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError(f"{label} claim is not an object")
    return claims


def _commit(report: dict) -> tuple[str | None, list]:
    if "commit" not in report:
        raise ValueError("archaeologist report is missing commit")
    commit = report.get("commit")
    if commit is not None and (not isinstance(commit, str) or not _HASH.fullmatch(commit)):
        raise ValueError("archaeologist commit is not a full hash")
    ranked = report.get("ranked")
    if not isinstance(ranked, list):
        raise ValueError("archaeologist report is missing ranked")
    if commit is None:
        if ranked:
            raise ValueError("archaeologist report ranks commits but names no commit")
        return None, []
    if not ranked:
        raise ValueError("archaeologist report names a commit but ranks none")
    return commit, ranked


def _line(ranked: list, commit: str | None) -> tuple[str | None, int | None, str | None]:
    if commit is None:
        return None, None, None
    row = ranked[0]
    if not isinstance(row, dict) or row.get("commit") != commit:
        raise ValueError("archaeologist top commit is not the first ranked commit")
    path = row.get("file")
    if path not in _FILES:
        raise ValueError("archaeologist file is not a service module")
    line = row.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        raise ValueError("archaeologist line is not a positive integer")
    text = row.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("archaeologist line text is empty")
    return path, line, text.strip()


def _parents(claims: list[dict], commit: str | None):
    commit_claim = None
    parent = None
    parent_claim = None
    parent_text = None
    for index, claim in enumerate(claims):
        for citation in claim.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            sha = citation.get("commit")
            if not isinstance(sha, str) or not _HASH.fullmatch(sha):
                continue
            if commit is not None and sha == commit and commit_claim is None:
                commit_claim = index
            elif parent is None and sha != commit:
                parent = sha
                parent_claim = index
                text = citation.get("text")
                if isinstance(text, str) and text.strip():
                    parent_text = text.strip()
    return parent, parent_claim, parent_text, commit_claim


def _first_log(claims: list[dict]) -> tuple[int | None, int | None]:
    for index, claim in enumerate(claims):
        timestamp = _log_timestamp(claim)
        if timestamp is not None:
            return index, timestamp
    return None, None


def _timeout_log(claims: list[dict]) -> tuple[int | None, int | None]:
    for index, claim in enumerate(claims):
        text = claim.get("text")
        if not isinstance(text, str) or "timed out" not in text:
            continue
        timestamp = _log_timestamp(claim)
        if timestamp is not None:
            return index, timestamp
    return None, None


def _log_timestamp(claim: dict) -> int | None:
    for citation in claim.get("citations") or []:
        if not isinstance(citation, dict) or citation.get("file") != "logs.jsonl":
            continue
        timestamp = citation.get("timestamp_unix_nano")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            continue
        return timestamp
    return None


def _shape(line: str | None, commit: str | None) -> str:
    """Classify the cited line. A caller deadline is not a duration constant.

    `PAYMENTS_TIMEOUT_MS` ends in `_MS`, and so does `WORK_MS`. The deadline
    form is checked first so a low caller timeout is not rolled back as if
    the dependency itself had gotten slower.
    """
    if commit is None:
        return "none"
    if not line:
        return "other"
    if _TIMEOUT_CONST.fullmatch(line):
        return "timeout_constant"
    if _DURATION.fullmatch(line):
        return "duration"
    if _CONSTANT.fullmatch(line):
        return "constant"
    if line.startswith("if ") and " not " in line:
        return "predicate"
    return "other"
