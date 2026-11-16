"""Code archaeologist over a log forensics report and the service history."""

from __future__ import annotations

from pathlib import Path

from code_archaeologist.history import open_repo
from code_archaeologist.llm import apply_summary
from code_archaeologist.load import read_profile
from code_archaeologist.rank import rank_commits
from code_archaeologist.report import build_report, no_incident

__version__ = "0.1.0"


def investigate(report: dict, history: Path | str | None = None) -> dict:
    """Rank commits for `report` and return a cited explanation.

    The report is deterministic unless CODE_ARCHAEOLOGIST_LLM selects a
    provider. ground_truth.json is not read. Commit subjects are not read.
    """
    profile = read_profile(report)
    if not profile.incident:
        return apply_summary(no_incident())
    checkout = open_repo(None if history is None else Path(history))
    try:
        ranked = rank_commits(profile, checkout.path)
        built = build_report(profile, ranked)
    finally:
        checkout.close()
    return apply_summary(built)
