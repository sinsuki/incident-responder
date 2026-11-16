"""Log forensics over one incident_sim telemetry directory."""

from __future__ import annotations

from pathlib import Path

from log_forensics.detect import build_checkouts, detect
from log_forensics.llm import apply_summary
from log_forensics.load import load_directory
from log_forensics.report import build_report

__version__ = "0.1.0"


def investigate(directory: Path | str) -> dict:
    """Read traces and logs in `directory` and return a cited incident report.

    The report is deterministic unless LOG_FORENSICS_LLM selects a provider.
    ground_truth.json is not read.
    """
    path = Path(directory)
    spans, logs = load_directory(path)
    checkouts = build_checkouts(spans, logs)
    finding = detect(checkouts)
    report = build_report(finding, checkouts)
    return apply_summary(report)
