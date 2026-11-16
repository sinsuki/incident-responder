"""Run the simulator, then forensics, the archaeologist, and the runbook agent.

Token totals are the usage fields those stages recorded, plus the
orchestrator's own usage when a model rewrote the sentences. This module
does not read ground_truth.json and does not estimate tokens.
"""

from __future__ import annotations

from pathlib import Path

from code_archaeologist import investigate as rank
from incident_sim.scenario import run
from log_forensics import investigate as read_incident
from runbook import recommend

from orchestrator.llm import apply_prose
from orchestrator.report import build_report


def respond(
    fault: str,
    seed: int,
    requests: int,
    warmup: int,
    out: Path | str,
    history: Path | str | None = None,
    runbooks: Path | str | None = None,
) -> dict:
    """Simulate `fault` into `out` and return the root-cause report."""
    out = Path(out)
    run(fault, seed, requests, warmup, out)
    return assemble(out, history, runbooks)


def assemble(
    directory: Path | str,
    history: Path | str | None = None,
    runbooks: Path | str | None = None,
) -> dict:
    """Build the report for a telemetry directory that already exists."""
    directory = Path(directory)
    forensics = read_incident(directory)
    archaeology = rank(forensics, history)
    book = recommend(forensics, archaeology, runbooks)
    report = build_report(forensics, archaeology, book)
    return apply_prose(report)
