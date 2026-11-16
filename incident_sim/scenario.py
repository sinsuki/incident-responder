"""Run a fixed number of checkouts and write ground truth next to the telemetry."""

from __future__ import annotations

import json
import random
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from incident_sim.checkout import response_code, run_checkout
from incident_sim.clock import GAP_NS, START_NS
from incident_sim.faults import FAULTS
from incident_sim.history import clone, fault_commit, load_revision
from incident_sim.telemetry import Session


@dataclass(frozen=True)
class Summary:
    fault: str
    seed: int
    out: Path
    spans: int
    logs: int
    metric_points: int
    wall_seconds: float
    deployed_commit: str
    started_at_unix_nano: int


def run(fault: str, seed: int, requests: int, warmup: int, out: Path) -> Summary:
    if requests < 1:
        raise ValueError("requests must be >= 1")
    if not 0 <= warmup < requests:
        raise ValueError("warmup must be >= 0 and less than requests")
    spec = FAULTS[fault]
    deployed = fault_commit(fault)
    if not deployed["parent"]:
        raise ValueError(f"{fault} has no parent commit")

    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        clone(repo)
        parent = load_revision(repo, deployed["parent"])
        revision = load_revision(repo, deployed["hash"])
        rng = random.Random(seed)
        clock = START_NS
        last_end = START_NS
        started_at = START_NS
        with Session(out, seed) as session:
            for index in range(requests):
                if index == warmup:
                    if warmup > 0:
                        session.collect(last_end)
                    started_at = clock
                active = parent if index < warmup else revision
                code = response_code(rng)
                last_end = run_checkout(session, active, index, code, clock)
                clock = last_end + GAP_NS
            session.collect(last_end)

    ground_truth = {
        "deployed_commit": deployed["hash"],
        "fault": spec.name,
        "marker": spec.marker,
        "parent_commit": deployed["parent"],
        "path": spec.path,
        "requests": requests,
        "seed": seed,
        "service": spec.service,
        "started_at_unix_nano": started_at,
        "summary": spec.summary,
        "warmup_requests": warmup,
    }
    (out / "ground_truth.json").write_text(
        json.dumps(ground_truth, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return Summary(
        fault=fault,
        seed=seed,
        out=out,
        spans=_lines(out / "traces.jsonl"),
        logs=_lines(out / "logs.jsonl"),
        metric_points=_lines(out / "metrics.jsonl"),
        wall_seconds=time.perf_counter() - started,
        deployed_commit=deployed["hash"],
        started_at_unix_nano=started_at,
    )


def _lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    if not text:
        return 0
    return text.count("\n")
