"""Command line for one scenario."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from incident_sim.faults import FAULTS
from incident_sim.scenario import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a checkout scenario and write OpenTelemetry files.")
    parser.add_argument("--fault", choices=sorted(FAULTS), help="Fault to deploy after the warmup.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--warmup", type=int, default=8, help="Checkouts served by the parent commit before the fault.")
    parser.add_argument("--out", type=Path, default=Path("runs/latest"))
    parser.add_argument("--list-faults", action="store_true")
    args = parser.parse_args(argv)

    if args.list_faults:
        for name in sorted(FAULTS):
            fault = FAULTS[name]
            print(f"{fault.name}\t{fault.service}\t{fault.summary}")
        return 0
    if not args.fault:
        parser.error("--fault is required")

    try:
        summary = run(args.fault, args.seed, args.requests, args.warmup, args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"fault {summary.fault}")
    print(f"seed {summary.seed}")
    print(f"commit {summary.deployed_commit}")
    print(f"started_at_unix_nano {summary.started_at_unix_nano}")
    print(f"out {summary.out}")
    print(f"spans {summary.spans}")
    print(f"logs {summary.logs}")
    print(f"metric_points {summary.metric_points}")
    print(f"wall_seconds {summary.wall_seconds:.4f}")
    return 0
