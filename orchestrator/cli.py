"""Command line for one fault scenario and its root-cause report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_archaeologist.history import open_repo
from incident_sim.faults import FAULTS

from orchestrator.check import check_report
from orchestrator.markdown import render
from orchestrator.pipeline import respond


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a fault scenario and write a cited root-cause report."
    )
    parser.add_argument("--fault", choices=sorted(FAULTS), required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=8)
    parser.add_argument("--out", type=Path, default=Path("runs/latest"))
    parser.add_argument(
        "--history",
        type=Path,
        help="Git checkout or bundle. Defaults to sample_history/shop.bundle.",
    )
    parser.add_argument("--runbooks", type=Path, help="Runbook directory. Defaults to runbooks/.")
    args = parser.parse_args(argv)

    try:
        report = respond(
            args.fault,
            args.seed,
            args.requests,
            args.warmup,
            args.out,
            args.history,
            args.runbooks,
        )
        checkout = open_repo(args.history)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        problems = check_report(report, args.out, checkout.path, args.runbooks)
    finally:
        checkout.close()

    _write(args.out, report)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


def _write(out: Path, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "rca.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "rca.md").write_text(render(report), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
