"""Telemetry files exist and the ids line up."""

import subprocess
import sys
from pathlib import Path

from incident_sim.clock import START_NS
from incident_sim.scenario import run
from tests.helpers import load_run

ROOT = Path(__file__).resolve().parents[1]
WINDOW_NS = 120 * 1_000_000_000


def test_cli_writes_a_run(tmp_path):
    out = tmp_path / "run"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "incident_sim",
            "--fault",
            "latency_spike",
            "--seed",
            "1",
            "--requests",
            "6",
            "--warmup",
            "2",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "spans " in completed.stdout
    assert (out / "traces.jsonl").stat().st_size > 0
    assert (out / "logs.jsonl").stat().st_size > 0
    assert (out / "metrics.jsonl").stat().st_size > 0
    assert (out / "ground_truth.json").stat().st_size > 0


def test_spans_logs_and_metrics_share_one_timeline(tmp_path):
    out = tmp_path / "run"
    run("error_rate_spike", seed=4, requests=10, warmup=3, out=out)
    data = load_run(out)
    traces = data["traces"]
    logs = data["logs"]
    metrics = data["metrics"]

    assert traces
    assert logs
    assert metrics
    spans = {span["span_id"]: span for span in traces}
    assert len(spans) == len(traces)

    for span in traces:
        assert len(span["trace_id"]) == 32
        assert len(span["span_id"]) == 16
        assert span["trace_id"] != "0" * 32
        assert _near_start(span["start_time_unix_nano"])
        assert _near_start(span["end_time_unix_nano"])
        assert span["end_time_unix_nano"] >= span["start_time_unix_nano"]

    for log in logs:
        assert log["timestamp_unix_nano"]
        assert len(log["trace_id"]) == 32
        assert len(log["span_id"]) == 16
        span = spans[log["span_id"]]
        assert log["trace_id"] == span["trace_id"]
        assert log["service"] == span["service"]
        assert span["start_time_unix_nano"] <= log["timestamp_unix_nano"] <= span["end_time_unix_nano"]
        assert _near_start(log["timestamp_unix_nano"])

    for point in metrics:
        assert point["service"] in {"gateway", "orders", "inventory", "payments"}
        assert point["name"] in {"requests", "duration_ms"}
        assert _near_start(point["time_unix_nano"])
        assert _near_start(point["start_time_unix_nano"])


def test_each_checkout_is_one_trace(tmp_path):
    requests = 5
    out = tmp_path / "run"
    run("bad_deploy", seed=2, requests=requests, warmup=1, out=out)
    traces = load_run(out)["traces"]
    by_trace: dict[str, list[dict]] = {}
    for span in traces:
        by_trace.setdefault(span["trace_id"], []).append(span)

    assert len(by_trace) == requests
    for spans in by_trace.values():
        assert len(spans) == 5
        roots = [span for span in spans if span["parent_span_id"] is None]
        assert len(roots) == 1
        assert roots[0]["name"] == "POST /checkout"
        assert roots[0]["service"] == "gateway"
        by_id = {span["span_id"]: span for span in spans}
        orders = _one(span for span in spans if span["name"] == "create_order")
        reserve = _one(span for span in spans if span["name"] == "reserve")
        client = _one(span for span in spans if span["name"] == "POST /charge" and span["kind"] == "CLIENT")
        server = _one(span for span in spans if span["name"] == "POST /charge" and span["kind"] == "SERVER")
        assert by_id[orders["parent_span_id"]]["name"] == "POST /checkout"
        assert reserve["parent_span_id"] == orders["span_id"]
        assert client["parent_span_id"] == orders["span_id"]
        assert server["parent_span_id"] == client["span_id"]
        assert reserve["service"] == "inventory"
        assert server["service"] == "payments"
        assert client["service"] == "orders"


def _near_start(timestamp: int) -> bool:
    return START_NS <= timestamp < START_NS + WINDOW_NS


def _one(spans) -> dict:
    found = list(spans)
    assert len(found) == 1
    return found[0]
