"""Score the orchestrator on root cause, mitigation, and citations.

A case scores 1 when the cited commit is the deployed commit, the service
matches, a replay of the mitigation steps leaves no incident, and every
citation resolves. The command runs all four faults with seeds 1 through 5.
Ground truth is deleted before the agents run.

    python -m orchestrator.eval
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
from runbook.apply import replay

from orchestrator.check import check_report
from orchestrator.pipeline import assemble
from orchestrator.tokens import pair

SEEDS = (1, 2, 3, 4, 5)
REQUESTS = 24
WARMUP = 8
_CODE = {"rollback", "revert_config", "raise_timeout"}
_PARTS = ("forensics", "archaeologist", "runbook", "orchestrator")


def score_case(report: dict, truth: dict, after: dict | None, problems: list[str]) -> dict:
    service_ok = report.get("service") == truth.get("service")
    commit_ok = bool(report.get("commit")) and report.get("commit") == truth.get("deployed_commit")
    root_cause_ok = bool(report.get("incident")) and service_ok and commit_ok
    matched = bool(report.get("matched"))
    cleared = matched and isinstance(after, dict) and after.get("incident") is False
    citation_ok = not problems
    passed = root_cause_ok and cleared and citation_ok
    tokens = report.get("tokens") if isinstance(report.get("tokens"), dict) else {}
    total = pair(tokens.get("total"))
    return {
        "root_cause_ok": root_cause_ok,
        "cleared": cleared,
        "citation_ok": citation_ok,
        "runbook": report.get("runbook"),
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "input_tokens": total["input"],
        "output_tokens": total["output"],
        "parts": {name: pair(tokens.get(name)) for name in _PARTS},
    }


def main() -> int:
    started = time.perf_counter()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        clone(repo)
        for fault in sorted(FAULTS):
            for seed in SEEDS:
                case_started = time.perf_counter()
                out = Path(tmp) / f"{fault}-{seed}"
                run(fault, seed, REQUESTS, WARMUP, out)
                truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
                (out / "ground_truth.json").unlink()
                report = assemble(out, repo)
                problems = check_report(report, out, repo)
                after = None
                if _replayable(report.get("steps") or []):
                    mitigated = out / "mitigated"
                    replay(report["steps"], seed, REQUESTS, WARMUP, mitigated)
                    after = read_incident(mitigated)
                scored = score_case(report, truth, after, problems)
                scored["fault"] = fault
                scored["seed"] = seed
                scored["runtime_seconds"] = time.perf_counter() - case_started
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
    print(
        f"{'fault':<22} {'seed':>4} {'root_cause':>11} {'cleared':>8} "
        f"{'citations':>10} {'score':>6} {'runtime_s':>10} {'tokens':>8}"
    )
    for row in rows:
        root = "yes" if row["root_cause_ok"] else "no"
        cleared = "yes" if row["cleared"] else "no"
        cites = "ok" if row["citation_ok"] else "FAIL"
        tokens = row["input_tokens"] + row["output_tokens"]
        print(
            f"{row['fault']:<22} {row['seed']:>4} {root:>11} {cleared:>8} "
            f"{cites:>10} {row['score']:6.3f} {row['runtime_seconds']:10.3f} {tokens:8d}"
        )
    print()
    for fault in sorted({row["fault"] for row in rows}):
        group = [row for row in rows if row["fault"] == fault]
        root = sum(1 for row in group if row["root_cause_ok"])
        cleared = sum(1 for row in group if row["cleared"])
        cites = sum(1 for row in group if row["citation_ok"])
        mean = sum(row["score"] for row in group) / len(group)
        names = sorted({row["runbook"] or "-" for row in group})
        print(
            f"{fault}: runbook {', '.join(names)}  root_cause {root}/{len(group)}  "
            f"cleared {cleared}/{len(group)}  citations {cites}/{len(group)}  mean_score {mean:.3f}"
        )
    count = len(rows)
    root_n = sum(1 for row in rows if row["root_cause_ok"])
    cleared_n = sum(1 for row in rows if row["cleared"])
    cite_n = sum(1 for row in rows if row["citation_ok"])
    passed = sum(1 for row in rows if row["passed"])
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    runtime = sum(row["runtime_seconds"] for row in rows)
    print(
        f"root_cause {root_n}/{count}  cleared {cleared_n}/{count}  citations {cite_n}/{count}  "
        f"passed {passed}/{count}  wall_seconds {wall_seconds:.3f}  "
        f"case_seconds {runtime:.3f}  input_tokens {input_tokens}  output_tokens {output_tokens}"
    )
    parts = []
    for name in _PARTS:
        part_in = sum(row["parts"][name]["input"] for row in rows)
        part_out = sum(row["parts"][name]["output"] for row in rows)
        parts.append(f"{name} {part_in}/{part_out}")
    print("tokens " + "  ".join(parts))


if __name__ == "__main__":
    raise SystemExit(main())
