"""Score mitigation by replaying it in the simulator.

A case scores 1 when the runbook steps clear the incident and every
citation resolves. Clearing means a second log-forensics pass, on a
checkout with those steps applied, reports no incident. The command runs
the simulator, log forensics, the archaeologist, and the runbook agent.
Ground truth is deleted before the agents run.

    python -m runbook.eval
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from code_archaeologist import investigate as rank
from incident_sim.faults import FAULTS
from incident_sim.history import clone
from incident_sim.scenario import run
from log_forensics import investigate as read_incident

from runbook import recommend
from runbook.apply import replay
from runbook.check import check_citations

SEEDS = (1, 2, 3, 4, 5)
REQUESTS = 24
WARMUP = 8
_CODE = {"rollback", "revert_config", "raise_timeout"}


def score_case(report: dict, after: dict | None, problems: list[str]) -> dict:
    matched = bool(report.get("matched"))
    gone = isinstance(after, dict) and after.get("incident") is False
    cleared = matched and gone
    citation_ok = not problems
    tokens = report.get("tokens") or {}
    return {
        "matched": matched,
        "cleared": cleared,
        "citation_ok": citation_ok,
        "runbook": report.get("runbook"),
        "score": 1.0 if cleared and citation_ok else 0.0,
        "passed": cleared and citation_ok,
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
                truth = out / "ground_truth.json"
                if truth.exists():
                    truth.unlink()
                forensics = read_incident(out)
                archaeology = rank(forensics, repo)
                report = recommend(forensics, archaeology)
                problems = check_citations(report, forensics, archaeology)
                after = None
                if _replayable(report.get("steps") or []):
                    mitigated = out / "mitigated"
                    replay(report["steps"], seed, REQUESTS, WARMUP, mitigated)
                    after = read_incident(mitigated)
                scored = score_case(report, after, problems)
                scored["fault"] = fault
                scored["seed"] = seed
                rows.append(scored)
    wall = time.perf_counter() - started
    _print(rows, wall)
    if all(row["passed"] for row in rows):
        return 0
    return 1


def _replayable(steps: list) -> bool:
    commits = set()
    parents = set()
    code = False
    for step in steps:
        if not isinstance(step, dict):
            return False
        if step.get("action") in _CODE:
            code = True
        target = step.get("target") if isinstance(step.get("target"), dict) else {}
        if target.get("commit"):
            commits.add(target["commit"])
        if target.get("parent"):
            parents.add(target["parent"])
    return code and len(commits) == 1 and len(parents) == 1


def _print(rows: list[dict], wall_seconds: float) -> None:
    print(f"{'fault':<22} {'seed':>4} {'runbook':<20} {'cleared':>7} {'score':>6} {'citations':>10}")
    for row in rows:
        cleared = "yes" if row["cleared"] else "no"
        cites = "ok" if row["citation_ok"] else "FAIL"
        runbook = row["runbook"] or "-"
        print(
            f"{row['fault']:<22} {row['seed']:>4} {runbook:<20} {cleared:>7} {row['score']:6.3f} {cites:>10}"
        )
    print()
    for fault in sorted({row["fault"] for row in rows}):
        group = [row for row in rows if row["fault"] == fault]
        cleared = sum(1 for row in group if row["cleared"])
        names = sorted({row["runbook"] or "-" for row in group})
        mean = sum(row["score"] for row in group) / len(group)
        print(f"{fault}: runbook {', '.join(names)}  cleared {cleared}/{len(group)}  mean_score {mean:.3f}")
    count = len(rows)
    cleared_n = sum(1 for row in rows if row["cleared"])
    passed = sum(1 for row in rows if row["passed"])
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    rate = cleared_n / count if count else 0.0
    print(
        f"cleared {cleared_n}/{count}  mitigation_success_rate {rate:.3f}  "
        f"passed {passed}/{count}  wall_seconds {wall_seconds:.3f}  "
        f"input_tokens {input_tokens}  output_tokens {output_tokens}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
