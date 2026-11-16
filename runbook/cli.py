"""Command line for one incident: forensics report plus archaeologist report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_archaeologist import investigate as rank
from log_forensics import investigate as read_incident

from runbook import recommend
from runbook.check import check_citations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pick cited mitigation steps for a forensics incident.")
    parser.add_argument(
        "source",
        type=Path,
        help="A telemetry directory, or a log forensics JSON report.",
    )
    parser.add_argument(
        "archaeology",
        nargs="?",
        type=Path,
        help="Archaeologist JSON report. Required when source is a file.",
    )
    parser.add_argument("--out", type=Path, help="Also write the JSON report to this path.")
    parser.add_argument(
        "--history",
        type=Path,
        help="Git checkout or bundle for the archaeologist. Defaults to sample_history/shop.bundle.",
    )
    parser.add_argument("--runbooks", type=Path, help="Runbook directory. Defaults to runbooks/.")
    args = parser.parse_args(argv)

    if args.source.is_dir() and args.archaeology is not None:
        parser.error("do not pass an archaeologist report when source is a directory")
    if not args.source.is_dir() and args.archaeology is None:
        parser.error("an archaeologist report is required when source is a file")

    try:
        if args.source.is_dir():
            forensics = read_incident(args.source)
            archaeology = rank(forensics, args.history)
        else:
            forensics = _json(args.source, "forensics")
            archaeology = _json(args.archaeology, "archaeologist")
        report = recommend(forensics, archaeology, args.runbooks)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    problems = check_citations(report, forensics, archaeology, args.runbooks)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


def _json(path: Path, label: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"not found: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not JSON") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{path} is not a {label} report")
    return report
