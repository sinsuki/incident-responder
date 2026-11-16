"""Turn ranked commits into the JSON report a later agent can read."""

from __future__ import annotations

from code_archaeologist.load import Profile
from code_archaeologist.rank import Candidate


def no_incident() -> dict:
    return {
        "schema_version": 1,
        "incident": False,
        "service": None,
        "kind": None,
        "started_at_unix_nano": None,
        "commit": None,
        "score": None,
        "summary": "No incident to attribute.",
        "ranked": [],
        "claims": [],
        "tokens": {"input": 0, "output": 0},
    }


def build_report(profile: Profile, ranked: list[Candidate]) -> dict:
    if not ranked:
        return {
            "schema_version": 1,
            "incident": True,
            "service": profile.service,
            "kind": profile.kind,
            "started_at_unix_nano": profile.started_at_unix_nano,
            "commit": None,
            "score": None,
            "summary": f"No commit that changes {profile.service}.py explains this {profile.kind}.",
            "ranked": [],
            "claims": [],
            "tokens": {"input": 0, "output": 0},
        }
    top = ranked[0]
    return {
        "schema_version": 1,
        "incident": True,
        "service": profile.service,
        "kind": profile.kind,
        "started_at_unix_nano": profile.started_at_unix_nano,
        "commit": top.commit,
        "score": top.score,
        "summary": _summary(profile, top),
        "ranked": [_row(item) for item in ranked],
        "claims": _claims(profile, top),
        "tokens": {"input": 0, "output": 0},
    }


def _row(item: Candidate) -> dict:
    return {
        "commit": item.commit,
        "file": item.file,
        "line": item.line,
        "score": item.score,
        "text": item.line_text,
    }


def _summary(profile: Profile, top: Candidate) -> str:
    where = f"{top.file}:{top.line} in {top.commit}"
    if top.label == "duration":
        text = (
            f"{profile.service} {profile.kind} matches {where} ({top.line_text}). "
            f"The forensics report shows a move from {_num(profile.baseline_ms)}ms "
            f"to {_num(profile.incident_ms)}ms."
        )
    elif top.label == "constant":
        text = f"The new error matches {where} ({top.line_text}). {top.detail}"
    elif top.label == "predicate":
        text = (
            f"The new error matches {where}, which changes the check to `{top.line_text}`. "
            f"That check guards {profile.signature!r}."
        )
    else:
        text = f"The strongest edit to {top.file} is {where} ({top.line_text}), with score {top.score}."
    if top.parent and top.parent_text:
        text += f" The parent {top.parent} has {top.parent_text}."
    if top.label == "duration" and top.detail:
        text += " " + top.detail
    return text


def _claims(profile: Profile, top: Candidate) -> list[dict]:
    claims = [
        {
            "text": _lead(profile, top),
            "citations": _lead_citations(top),
        }
    ]
    if top.parent and top.parent_line and top.parent_text:
        claims.append(
            {
                "text": (
                    f"Before {top.commit}, {top.parent} has `{top.parent_text}` "
                    f"at {top.file}:{top.parent_line}."
                ),
                "citations": [
                    _cite(top.parent, top.file, top.parent_line, top.parent_text),
                ],
            }
        )
    return claims


def _lead(profile: Profile, top: Candidate) -> str:
    where = f"{top.file}:{top.line}"
    blame = f"git blame attributes {where} to {top.commit}."
    if top.label == "duration":
        text = (
            f"{where} at {top.commit} sets {top.line_text}. {blame} "
            f"The forensics report shows {profile.service} moving from "
            f"{_num(profile.baseline_ms)}ms to {_num(profile.incident_ms)}ms."
        )
        if top.detail:
            text += " " + top.detail
        return text
    if top.label == "constant":
        text = f"{where} at {top.commit} sets {top.line_text}. {blame} {top.detail}"
        if top.extra:
            line, line_text = top.extra[0]
            text += f" The range check is {top.file}:{line}: `{line_text}`."
        return text
    if top.label == "predicate":
        return (
            f"{where} at {top.commit} changes the check to `{top.line_text}`. {blame} "
            f"That check guards the new error {profile.signature!r}."
        )
    return f"{where} at {top.commit} is `{top.line_text}`. {blame}"


def _lead_citations(top: Candidate) -> list[dict]:
    citations = [_cite(top.commit, top.file, top.line, top.line_text)]
    for line, text in top.extra:
        citations.append(_cite(top.commit, top.file, line, text))
    return citations


def _cite(commit: str, path: str, line: int, text: str) -> dict:
    return {"commit": commit, "file": path, "line": line, "text": text}


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"
