"""Every cited commit must exist, and every file:line must exist there.

The citation text, when present, has to be that line. The ranked list is
checked the same way, so a hash or a line that is not in the history does
not resolve.
"""

from __future__ import annotations

import re
from pathlib import Path

from code_archaeologist.history import file_at, is_commit

_HASH = re.compile(r"^[0-9a-f]{40}$")


def check_citations(report: dict, repo: Path | str) -> list[str]:
    """Return one problem string per claim or citation that does not resolve.

    An empty list means every cited commit is in the history and every
    file:line exists at that commit.
    """
    repo = Path(repo)
    if not isinstance(report, dict):
        return ["report is not an object"]
    claims = report.get("claims")
    ranked = report.get("ranked")
    if not isinstance(claims, list):
        return ["report claims are not a list"]
    if not isinstance(ranked, list):
        return ["report ranked is not a list"]

    problems = []
    commit = report.get("commit")
    if commit is None:
        if claims:
            problems.append("report has claims but names no commit")
        if ranked:
            problems.append("report ranks commits but names no commit")
    else:
        if not _HASH.fullmatch(str(commit)):
            problems.append("top commit is not a full hash")
        if not claims:
            problems.append("report names a commit but has no claims")
        if not ranked or not isinstance(ranked[0], dict) or ranked[0].get("commit") != commit:
            problems.append("top commit is not the first ranked commit")

    cited = set()
    saw_line = False
    for index, claim in enumerate(claims):
        claim_problems, hashes, had_line = _check_claim(repo, index, claim)
        problems.extend(claim_problems)
        cited |= hashes
        saw_line = saw_line or had_line
    if commit and commit not in cited:
        problems.append("top commit is not cited")
    if commit and claims and not saw_line and not any("does not resolve" in item for item in problems):
        problems.append("report cites no file line")

    for index, row in enumerate(ranked):
        problems.extend(_check_ranked(repo, index, row))
    return problems


def _check_claim(repo: Path, index: int, claim) -> tuple[list[str], set[str], bool]:
    if not isinstance(claim, dict):
        return [f"claim {index} does not resolve: claim is not an object"], set(), False
    text = claim.get("text")
    if not isinstance(text, str) or not text.strip():
        return [f"claim {index} does not resolve: claim has no text"], set(), False
    citations = claim.get("citations")
    if not isinstance(citations, list) or not citations:
        return [f"claim {index} does not resolve: claim has no citations"], set(), False
    problems = []
    hashes = set()
    saw_line = False
    for citation in citations:
        problem, sha, had_line = _resolve(repo, citation)
        if problem:
            problems.append(f"claim {index} does not resolve: {problem}")
            continue
        if sha:
            hashes.add(sha)
        saw_line = saw_line or had_line
    return problems, hashes, saw_line


def _check_ranked(repo: Path, index: int, row) -> list[str]:
    if not isinstance(row, dict):
        return [f"ranked {index} does not resolve: entry is not an object"]
    problem, _, _ = _resolve(repo, row)
    if problem:
        return [f"ranked {index} does not resolve: {problem}"]
    return []


def _resolve(repo: Path, citation) -> tuple[str | None, str | None, bool]:
    if not isinstance(citation, dict):
        return "citation is not an object", None, False
    sha = citation.get("commit")
    if not isinstance(sha, str) or not _HASH.fullmatch(sha):
        return "citation commit is not a full hash", None, False
    if not is_commit(repo, sha):
        return f"commit {sha} is not in the history", None, False
    path = citation.get("file")
    path_problem = _bad_path(path)
    if path_problem:
        return path_problem, sha, False
    line = citation.get("line")
    if isinstance(line, bool) or not isinstance(line, int) or line < 1:
        return "citation line is not a positive integer", sha, False
    text = file_at(repo, sha, path)
    if text is None:
        return f"{path} is not in {sha}", sha, False
    lines = text.splitlines()
    if line > len(lines):
        return f"{path}:{line} is past the end of the file at {sha}", sha, False
    expected = citation.get("text")
    if not isinstance(expected, str) or not expected.strip():
        return "citation has no line text", sha, False
    actual = lines[line - 1].strip()
    if actual != expected:
        return f"{path}:{line} text does not match", sha, False
    return None, sha, True


def _bad_path(path) -> str | None:
    if not isinstance(path, str) or not path or path.startswith("/") or path.startswith("\\"):
        return "citation file is not a path in the commit"
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return "citation file is not a path in the commit"
    return None
