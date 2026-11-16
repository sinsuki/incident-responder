"""The forensics agent names the service and the onset, without a model."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from incident_sim.faults import FAULTS
from incident_sim.scenario import run
from log_forensics import investigate
from log_forensics.check import check_citations
from log_forensics.llm import apply_summary, evidence_digest
from tests.helpers import load_run

ROOT = Path(__file__).resolve().parents[1]
FAULT_NAMES = sorted(FAULTS)
SEEDS = (1, 2, 3)


@pytest.mark.parametrize("fault", FAULT_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_detects_the_fault_service_and_onset(tmp_path, fault, seed, monkeypatch):
    monkeypatch.delenv("LOG_FORENSICS_LLM", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / fault
    run(fault, seed=seed, requests=24, warmup=8, out=out)
    truth = load_run(out)["ground_truth"]
    # A wrong ground-truth file must not affect the report.
    (out / "ground_truth.json").write_text('{"service": "gateway"}\n', encoding="utf-8")

    report = investigate(out)

    assert report["incident"] is True
    assert report["service"] == truth["service"]
    assert report["kind"] in {"latency", "timeout", "error_rate"}
    assert report["tokens"] == {"input": 0, "output": 0}
    delta_ms = abs(report["started_at_unix_nano"] - truth["started_at_unix_nano"]) / 1_000_000
    assert delta_ms <= 1000
    assert check_citations(report, out) == []
    _assert_kind(fault, report)
    _assert_claims_cite_logs(report)


def test_same_directory_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.delenv("LOG_FORENSICS_LLM", raising=False)
    out = tmp_path / "run"
    run("bad_deploy", seed=4, requests=16, warmup=6, out=out)
    assert investigate(out) == investigate(out)


@pytest.mark.parametrize("seed", (1, 3, 37))
def test_healthy_run_reports_no_incident(tmp_path, seed):
    out = _healthy(tmp_path, seed)
    report = investigate(out)
    assert report["incident"] is False
    assert report["service"] is None
    assert report["kind"] is None
    assert report["started_at_unix_nano"] is None
    assert report["claims"] == []
    assert report["tokens"] == {"input": 0, "output": 0}
    assert check_citations(report, out) == []


def test_short_run_is_not_called_an_incident(tmp_path):
    raw = tmp_path / "raw"
    run("error_rate_spike", seed=1, requests=10, warmup=6, out=raw)
    out = _truncate_before_fault(raw, tmp_path / "short", keep=5)
    report = investigate(out)
    assert report["incident"] is False
    assert check_citations(report, out) == []


def test_missing_traces_fail(tmp_path):
    (tmp_path / "logs.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="traces.jsonl"):
        investigate(tmp_path)


def test_bad_json_line_fails(tmp_path):
    (tmp_path / "traces.jsonl").write_text("{not json}\n", encoding="utf-8")
    (tmp_path / "logs.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        investigate(tmp_path)


def test_cli_writes_a_cited_report(tmp_path):
    out = tmp_path / "run"
    report_path = tmp_path / "report.json"
    run("latency_spike", seed=1, requests=16, warmup=6, out=out)
    completed = subprocess.run(
        [sys.executable, "-m", "log_forensics", str(out), "--out", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["service"] == "inventory"
    assert report["kind"] == "latency"
    assert report["tokens"] == {"input": 0, "output": 0}
    assert json.loads(completed.stdout) == report


def test_cli_missing_directory_exits_2(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "log_forensics", str(tmp_path / "missing")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "traces.jsonl" in completed.stderr


def test_unknown_llm_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_FORENSICS_LLM", "made-up")
    with pytest.raises(ValueError, match="unknown LOG_FORENSICS_LLM"):
        apply_summary(_empty_report())


def test_openai_without_a_key_is_rejected(monkeypatch):
    monkeypatch.setenv("LOG_FORENSICS_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        apply_summary(_empty_report())


def test_digest_is_the_report_facts_not_a_telemetry_file(tmp_path):
    out = tmp_path / "run"
    run("dependency_timeout", seed=1, requests=12, warmup=4, out=out)
    report = investigate(out)
    digest = evidence_digest(report)
    assert set(digest) == {"claims", "incident", "kind", "service", "started_at_unix_nano", "stats"}
    encoded = json.dumps(digest)
    assert "bucket_counts" not in encoded
    assert len(encoded) < 8000


def _assert_kind(fault, report):
    if fault == "latency_spike":
        assert report["kind"] == "latency"
        assert report["stats"]["incident_duration_ms"] > report["stats"]["baseline_duration_ms"]
    elif fault == "dependency_timeout":
        assert report["kind"] == "timeout"
        assert "timed out" in report["stats"]["signature"]
    elif fault == "error_rate_spike":
        assert report["kind"] == "error_rate"
        assert "processor code 00" in report["stats"]["signature"]
    elif fault == "bad_deploy":
        assert report["kind"] == "error_rate"
        assert "amount out of range" in report["stats"]["signature"]


def _assert_claims_cite_logs(report):
    assert report["claims"]
    for claim in report["claims"]:
        assert claim["text"]
        logs = [citation for citation in claim["citations"] if citation["file"] == "logs.jsonl"]
        assert logs
        for citation in claim["citations"]:
            assert citation["trace_id"]
            assert citation["span_id"]
            assert isinstance(citation["timestamp_unix_nano"], int)
            assert isinstance(citation["line"], int)


def _healthy(tmp_path, seed):
    raw = tmp_path / f"raw-{seed}"
    run("latency_spike", seed=seed, requests=24, warmup=16, out=raw)
    return _truncate_before_fault(raw, tmp_path / f"healthy-{seed}")


def _truncate_before_fault(raw: Path, dest: Path, keep: int | None = None) -> Path:
    data = load_run(raw)
    started = data["ground_truth"]["started_at_unix_nano"]
    traces = [span for span in data["traces"] if span["end_time_unix_nano"] < started]
    logs = [log for log in data["logs"] if log["timestamp_unix_nano"] < started]
    if keep is not None:
        order = []
        for span in traces:
            order_id = span["attributes"].get("order.id")
            if order_id not in order:
                order.append(order_id)
        allowed = set(order[:keep])
        traces = [span for span in traces if span["attributes"].get("order.id") in allowed]
        logs = [log for log in logs if log["attributes"].get("order.id") in allowed]
    dest.mkdir(parents=True)
    _write_jsonl(dest / "traces.jsonl", traces)
    _write_jsonl(dest / "logs.jsonl", logs)
    return dest


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _empty_report():
    return {
        "claims": [],
        "incident": False,
        "kind": None,
        "service": None,
        "started_at_unix_nano": None,
        "stats": None,
        "summary": "No error-rate or latency spike found.",
        "tokens": {"input": 0, "output": 0},
    }
