"""The archaeologist names the deployed commit without reading ground truth."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from code_archaeologist import investigate
from code_archaeologist.check import check_citations
from code_archaeologist.history import commits_touching, open_repo
from code_archaeologist.llm import apply_summary, evidence_digest
from incident_sim.faults import FAULTS
from incident_sim.history import clone
from incident_sim.scenario import run
from log_forensics import investigate as read_incident
from tests.helpers import load_run

ROOT = Path(__file__).resolve().parents[1]
FAULT_NAMES = sorted(FAULTS)
SEEDS = (1, 2)


@pytest.mark.parametrize("fault", FAULT_NAMES)
@pytest.mark.parametrize("seed", SEEDS)
def test_top_commit_is_the_deployed_commit(tmp_path, fault, seed, monkeypatch):
    monkeypatch.delenv("CODE_ARCHAEOLOGIST_LLM", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = tmp_path / fault
    run(fault, seed=seed, requests=24, warmup=8, out=out)
    truth = load_run(out)["ground_truth"]
    forensics = read_incident(out)
    forensics["deployed_commit"] = "f" * 40
    forensics["marker"] = truth["marker"]
    (out / "ground_truth.json").write_text('{"deployed_commit": "gateway"}\n', encoding="utf-8")

    report = investigate(forensics)
    checkout = open_repo()
    try:
        problems = check_citations(report, checkout.path)
    finally:
        checkout.close()

    assert report["commit"] == truth["deployed_commit"]
    assert report["service"] == truth["service"]
    assert report["kind"] == forensics["kind"]
    assert report["tokens"] == {"input": 0, "output": 0}
    assert problems == []
    assert len(report["ranked"]) >= 3
    assert report["ranked"][0]["commit"] == report["commit"]
    assert report["score"] > report["ranked"][1]["score"]
    assert truth["deployed_commit"] not in {row["commit"] for row in report["ranked"][1:]}
    _assert_claims(report)


def test_same_report_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.delenv("CODE_ARCHAEOLOGIST_LLM", raising=False)
    out = tmp_path / "run"
    run("bad_deploy", seed=4, requests=16, warmup=6, out=out)
    forensics = read_incident(out)
    assert investigate(forensics) == investigate(forensics)


def test_no_incident_names_no_commit(monkeypatch):
    monkeypatch.delenv("CODE_ARCHAEOLOGIST_LLM", raising=False)
    report = investigate(
        {
            "incident": False,
            "service": None,
            "kind": None,
            "started_at_unix_nano": None,
            "stats": None,
            "claims": [],
            "summary": "No error-rate or latency spike found.",
            "tokens": {"input": 0, "output": 0},
        }
    )
    assert report["incident"] is False
    assert report["commit"] is None
    assert report["ranked"] == []
    assert report["claims"] == []
    assert report["tokens"] == {"input": 0, "output": 0}


def test_healthy_directory_names_no_commit(tmp_path):
    raw = tmp_path / "raw"
    run("latency_spike", seed=1, requests=24, warmup=16, out=raw)
    out = _before_fault(raw, tmp_path / "healthy")
    forensics = read_incident(out)
    assert forensics["incident"] is False
    report = investigate(forensics)
    assert report["commit"] is None
    assert report["claims"] == []


def test_commit_listing_is_hashes_only(tmp_path):
    repo = tmp_path / "repo"
    clone(repo)
    rows = commits_touching(repo, "payments.py")
    assert len(rows) >= 4
    for commit, parent in rows:
        assert len(commit) == 40
        assert parent is None or len(parent) == 40
        assert " " not in commit


def test_missing_stats_fail():
    with pytest.raises(ValueError, match="stats"):
        investigate(
            {
                "incident": True,
                "service": "payments",
                "kind": "error_rate",
                "started_at_unix_nano": 1,
            }
        )


def test_unknown_service_fails():
    with pytest.raises(ValueError, match="service"):
        investigate(_incident_report(service="billing"))


def test_cli_writes_a_cited_report(tmp_path):
    out = tmp_path / "run"
    report_path = tmp_path / "report.json"
    run("latency_spike", seed=1, requests=16, warmup=6, out=out)
    truth = load_run(out)["ground_truth"]
    (out / "ground_truth.json").write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "code_archaeologist", str(out), "--out", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["commit"] == truth["deployed_commit"]
    assert report["tokens"] == {"input": 0, "output": 0}
    assert json.loads(completed.stdout) == report


def test_cli_missing_directory_exits_2(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "code_archaeologist", str(tmp_path / "missing")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "not found" in completed.stderr


def test_cli_rejects_a_non_object_report(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("[]\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "code_archaeologist", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_unknown_llm_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("CODE_ARCHAEOLOGIST_LLM", "made-up")
    with pytest.raises(ValueError, match="unknown CODE_ARCHAEOLOGIST_LLM"):
        apply_summary(_blank())


def test_openai_without_a_key_is_rejected(monkeypatch):
    monkeypatch.setenv("CODE_ARCHAEOLOGIST_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        apply_summary(_blank())


def test_digest_is_the_ranked_facts_not_the_source_or_the_subject(tmp_path):
    out = tmp_path / "run"
    run("bad_deploy", seed=1, requests=12, warmup=4, out=out)
    report = investigate(read_incident(out))
    digest = evidence_digest(report)
    assert set(digest) == {"claims", "commit", "incident", "kind", "ranked", "score", "service"}
    encoded = json.dumps(digest)
    assert "deployed_commit" not in encoded
    assert "ground_truth" not in encoded
    assert "update charge amount handling" not in encoded
    assert "def format_receipt" not in encoded
    assert len(encoded) < 8000


def _assert_claims(report):
    assert report["claims"]
    cited = set()
    for claim in report["claims"]:
        assert claim["text"]
        assert claim["citations"]
        for citation in claim["citations"]:
            assert len(citation["commit"]) == 40
            assert citation["file"].endswith(".py")
            assert citation["line"] >= 1
            assert citation["text"]
            cited.add(citation["commit"])
    assert report["commit"] in cited
    assert report["commit"] in report["claims"][0]["text"]


def _before_fault(raw: Path, dest: Path) -> Path:
    data = load_run(raw)
    started = data["ground_truth"]["started_at_unix_nano"]
    traces = [row for row in data["traces"] if row["end_time_unix_nano"] < started]
    logs = [row for row in data["logs"] if row["timestamp_unix_nano"] < started]
    dest.mkdir()
    _write(dest / "traces.jsonl", traces)
    _write(dest / "logs.jsonl", logs)
    return dest


def _write(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _incident_report(service="payments"):
    return {
        "incident": True,
        "service": service,
        "kind": "error_rate",
        "started_at_unix_nano": 1,
        "stats": {
            "baseline_duration_ms": 48,
            "incident_duration_ms": 48,
            "signature": "charge failed: processor code 00",
        },
    }


def _blank():
    return {
        "claims": [],
        "commit": None,
        "incident": False,
        "kind": None,
        "ranked": [],
        "score": None,
        "service": None,
        "summary": "No incident to attribute.",
        "tokens": {"input": 0, "output": 0},
    }
