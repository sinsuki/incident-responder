"""Order the commits that touch the implicated service.

The subject line is not available here. `commits_touching` yields hashes,
`score_pair` reads the two file versions, and `git blame` has to attribute
the chosen line to that same commit.
"""

from __future__ import annotations

from dataclasses import dataclass

from code_archaeologist.history import blame_line, commits_touching, file_at
from code_archaeologist.load import Profile
from code_archaeologist.score import Explanation, score_pair


@dataclass(frozen=True)
class Candidate:
    commit: str
    parent: str | None
    score: float
    file: str
    line: int
    line_text: str
    parent_line: int | None
    parent_text: str | None
    label: str
    detail: str
    extra: tuple[tuple[int, str], ...]


def rank_commits(profile: Profile, repo) -> list[Candidate]:
    path = f"{profile.service}.py"
    ranked = []
    for commit, parent in commits_touching(repo, path):
        if parent is None:
            continue
        new = file_at(repo, commit, path)
        old = file_at(repo, parent, path)
        if new is None or old is None:
            continue
        explained = score_pair(profile, old, new)
        if explained is None or explained.score <= 0:
            continue
        if blame_line(repo, commit, path, explained.line) != commit:
            continue
        ranked.append(_candidate(commit, parent, path, explained))
    ranked.sort(key=lambda item: (-item.score, item.commit))
    return ranked


def _candidate(commit: str, parent: str | None, path: str, explained: Explanation) -> Candidate:
    return Candidate(
        commit=commit,
        parent=parent,
        score=explained.score,
        file=path,
        line=explained.line,
        line_text=explained.line_text,
        parent_line=explained.parent_line,
        parent_text=explained.parent_text,
        label=explained.label,
        detail=explained.detail,
        extra=explained.extra,
    )
