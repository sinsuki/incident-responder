"""Command line for one telemetry directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from log_forensics import investigate
from log_forensics.check import check_citations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read one telemetry directory and report an error or latency spike."
    )
    parser.add_argument("directory", type=Path, help="Directory with traces.jsonl and logs.jsonl.")
    parser.add_argument("--out", type=Path, help="Also write the JSON report to this path.")
    args = parser.parse_args(argv)

    try:
        report = investigate(args.directory)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    problems = check_citations(report, args.directory)
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
