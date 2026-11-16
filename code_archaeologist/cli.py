"""Command line for one forensics report, or one telemetry directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_archaeologist import investigate
from code_archaeologist.check import check_citations
from code_archaeologist.history import open_repo
from log_forensics import investigate as read_incident


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank the commit most likely to have caused a forensics incident."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="A log forensics JSON report, or a telemetry directory to investigate first.",
    )
    parser.add_argument("--out", type=Path, help="Also write the JSON report to this path.")
    parser.add_argument(
        "--history",
        type=Path,
        help="Git checkout or bundle. Defaults to sample_history/shop.bundle.",
    )
    args = parser.parse_args(argv)

    try:
        report_in = _load(args.source)
        checkout = open_repo(args.history)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        try:
            report = investigate(report_in, checkout.path)
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        problems = check_citations(report, checkout.path)
    finally:
        checkout.close()

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


def _load(source: Path) -> dict:
    if source.is_dir():
        return read_incident(source)
    if not source.is_file():
        raise FileNotFoundError(f"not found: {source}")
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source} is not JSON") from exc
    if not isinstance(report, dict):
        raise ValueError(f"{source} is not a forensics report")
    return report
