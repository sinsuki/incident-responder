"""Check a saved root-cause report and exit 1 when a citation does not resolve.

    python -m orchestrator.verify rca.json --run runs/latency
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_archaeologist.history import open_repo

from orchestrator.check import check_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject an RCA whose claims do not resolve.")
    parser.add_argument("report", type=Path, help="rca.json written by the orchestrator.")
    parser.add_argument("--run", required=True, type=Path, help="Telemetry directory for that report.")
    parser.add_argument("--history", type=Path, help="Git checkout or bundle. Defaults to the sample bundle.")
    parser.add_argument("--runbooks", type=Path, help="Runbook directory. Defaults to runbooks/.")
    args = parser.parse_args(argv)

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("report is not an object", file=sys.stderr)
        return 2
    if not args.run.is_dir():
        print(f"not found: {args.run}", file=sys.stderr)
        return 2
    try:
        checkout = open_repo(args.history)
    except (FileNotFoundError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        problems = check_report(report, args.run, checkout.path, args.runbooks)
    finally:
        checkout.close()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
