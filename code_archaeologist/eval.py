"""Score the code archaeologist against the deployed commit.

A case scores 1 when the top commit is the ground-truth commit. Top-3 counts
a hit when that commit is one of the first three ranked commits. Pass means
the top commit matches and every citation resolves. The command runs the
simulator, then log forensics, then the archaeologist. Ground truth is read
only after both agents return.

    python -m code_archaeologist.eval
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from incident_sim.faults import FAULTS
from incident_sim.history import clone
from incident_sim.scenario import run
from log_forensics import investigate as read_incident

from code_archaeologist import investigate
from code_archaeologist.check import check_citations

SEEDS = (1, 2, 3, 4, 5)
REQUESTS = 24
WARMUP = 8


def score_case(report: dict, truth: dict) -> dict:
    ranked = report.get("ranked") or []
    hashes = [row.get("commit") for row in ranked if isinstance(row, dict)]
    top = report.get("commit")
    truth_commit = truth["deployed_commit"]
    top1 = top == truth_commit
    top3 = truth_commit in hashes[:3]
    tokens = report.get("tokens") or {}
    return {
        "top1": top1,
        "top3": top3,
        "predicted": top,
        "score": 1.0 if top1 else 0.0,
        "passed": top1,
        "input_tokens": int(tokens.get("input", 0)),
        "output_tokens": int(tokens.get("output", 0)),
    }


def main() -> int:
    started = time.perf_counter()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        clone(repo)
        for fault in sorted(FAULTS):
            for seed in SEEDS:
                out = Path(tmp) / f"{fault}-{seed}"
                run(fault, seed, REQUESTS, WARMUP, out)
                forensics = read_incident(out)
                truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
                (out / "ground_truth.json").write_text("{}\n", encoding="utf-8")
                report = investigate(forensics, repo)
                scored = score_case(report, truth)
                problems = check_citations(report, repo)
                scored["citation_ok"] = not problems
                if problems:
                    scored["passed"] = False
                    scored["score"] = 0.0
                scored["fault"] = fault
                scored["seed"] = seed
                rows.append(scored)
    wall = time.perf_counter() - started
    _print(rows, wall)
    if all(row["passed"] for row in rows):
        return 0
    return 1


def _print(rows: list[dict], wall_seconds: float) -> None:
    print(f"{'fault':<22} {'seed':>4} {'top1':>5} {'top3':>5} {'score':>6} {'citations':>10}  commit")
    for row in rows:
        top1 = "yes" if row["top1"] else "no"
        top3 = "yes" if row["top3"] else "no"
        cites = "ok" if row["citation_ok"] else "FAIL"
        commit = row["predicted"] or "-"
        print(
            f"{row['fault']:<22} {row['seed']:>4} {top1:>5} {top3:>5} {row['score']:6.3f} {cites:>10}  {commit}"
        )
    print()
    for fault in sorted({row["fault"] for row in rows}):
        group = [row for row in rows if row["fault"] == fault]
        top1 = sum(1 for row in group if row["top1"])
        top3 = sum(1 for row in group if row["top3"])
        print(f"{fault}: top1 {top1}/{len(group)}  top3 {top3}/{len(group)}")
    count = len(rows)
    top1_hits = sum(1 for row in rows if row["top1"])
    top3_hits = sum(1 for row in rows if row["top3"])
    passed = sum(1 for row in rows if row["passed"])
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    print(
        f"top1_accuracy {top1_hits / count:.3f}  top3_accuracy {top3_hits / count:.3f}  "
        f"passed {passed}/{count}  wall_seconds {wall_seconds:.3f}  "
        f"input_tokens {input_tokens}  output_tokens {output_tokens}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
