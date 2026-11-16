"""Score log forensics against ground truth for every fault.

A case scores 1 when the service matches and the onset is exact. The score
falls linearly to 0 at 1000ms of onset error. A wrong service scores 0.
Pass means the service matches, the onset is within 1000ms, and every
citation resolves.

    python -m log_forensics.eval
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from incident_sim.faults import FAULTS
from incident_sim.scenario import run

from log_forensics import investigate
from log_forensics.check import check_citations

SEEDS = (1, 2, 3, 4, 5)
REQUESTS = 24
WARMUP = 8
TOLERANCE_MS = 1000


def score_case(report: dict, truth: dict) -> dict:
    service = report.get("service")
    service_ok = bool(report.get("incident")) and service == truth["service"]
    predicted = report.get("started_at_unix_nano")
    if not report.get("incident") or predicted is None:
        delta_ms = None
        onset_score = 0.0
    else:
        delta_ms = abs(int(predicted) - int(truth["started_at_unix_nano"])) / 1_000_000
        onset_score = max(0.0, 1.0 - delta_ms / TOLERANCE_MS)
    tokens = report.get("tokens") or {}
    return {
        "service_ok": service_ok,
        "predicted_service": service,
        "onset_delta_ms": delta_ms,
        "score": onset_score if service_ok else 0.0,
        "passed": service_ok and delta_ms is not None and delta_ms <= TOLERANCE_MS,
        "input_tokens": int(tokens.get("input", 0)),
        "output_tokens": int(tokens.get("output", 0)),
    }


def main() -> int:
    started = time.perf_counter()
    rows = []
    for fault in sorted(FAULTS):
        for seed in SEEDS:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "run"
                run(fault, seed, REQUESTS, WARMUP, out)
                report = investigate(out)
                truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
                scored = score_case(report, truth)
                problems = check_citations(report, out)
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
    print(f"{'fault':<20} {'seed':>4} {'service':<12} {'hit':>3} {'delta_ms':>10} {'score':>7} {'citations':>10}")
    for row in rows:
        delta = "-" if row["onset_delta_ms"] is None else f"{row['onset_delta_ms']:.3f}"
        hit = "yes" if row["service_ok"] else "no"
        cites = "ok" if row["citation_ok"] else "FAIL"
        service = row["predicted_service"] or "-"
        print(
            f"{row['fault']:<20} {row['seed']:>4} {service:<12} {hit:>3} {delta:>10} {row['score']:7.3f} {cites:>10}"
        )
    print()
    for fault in sorted({row["fault"] for row in rows}):
        group = [row for row in rows if row["fault"] == fault]
        hits = sum(1 for row in group if row["service_ok"])
        deltas = [row["onset_delta_ms"] for row in group if row["service_ok"] and row["onset_delta_ms"] is not None]
        mean_delta = sum(deltas) / len(deltas) if deltas else float("nan")
        max_delta = max(deltas) if deltas else float("nan")
        mean_score = sum(row["score"] for row in group) / len(group)
        print(
            f"{fault}: service {hits}/{len(group)}  "
            f"mean_onset_delta_ms {mean_delta:.3f}  "
            f"max_onset_delta_ms {max_delta:.3f}  "
            f"mean_score {mean_score:.3f}"
        )
    passed = sum(1 for row in rows if row["passed"])
    input_tokens = sum(row["input_tokens"] for row in rows)
    output_tokens = sum(row["output_tokens"] for row in rows)
    print(
        f"passed {passed}/{len(rows)}  wall_seconds {wall_seconds:.3f}  "
        f"input_tokens {input_tokens}  output_tokens {output_tokens}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
