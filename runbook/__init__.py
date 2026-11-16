"""Runbook agent: cited mitigation steps for one incident.

Matching is deterministic. RUNBOOK_LLM may rewrite the summary.
ground_truth.json is not read.
"""

from __future__ import annotations

from pathlib import Path

from runbook.books import default_directory, load_runbooks
from runbook.llm import apply_summary
from runbook.load import read_case
from runbook.match import select
from runbook.report import build_report, no_incident, no_match

__version__ = "0.1.0"


def recommend(forensics: dict, archaeology: dict, runbooks: Path | str | None = None) -> dict:
    """Choose ordered mitigation steps for the two upstream reports.

    The report is deterministic unless RUNBOOK_LLM selects a provider.
    """
    case = read_case(forensics, archaeology)
    if not case.incident:
        return apply_summary(no_incident())
    directory = default_directory() if runbooks is None else Path(runbooks)
    choice = select(case, load_runbooks(directory))
    if choice.book is None:
        return apply_summary(no_match(case, choice.reason))
    return apply_summary(build_report(case, choice.book, choice.steps))
