"""The orchestrator writes one cited report and does not call a model by default."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from incident_sim.scenario import run
from orchestrator import assemble, respond
from orchestrator.check import check_report
from orchestrator.llm import apply_prose, evidence_digest
from orchestrator.markdown import render
from orchestrator.tokens import account

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "latency_spike"


def test_cli_writes_markdown_and_json(tmp_path):
    out = tmp_path / "run"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestrator",
            "--fault",
            "latency_spike",
            "--seed",
            "1",
            "--requests",
            "12",
            "--warmup",
            "4",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((out / "rca.json").read_text(encoding="utf-8"))
    assert json.loads(completed.stdout) == report
    markdown = (out / "rca.md").read_text(encoding="utf-8")
    assert markdown == render(report)
    for heading in ("## Summary", "## Impact", "## Timeline", "## Root cause", "## Evidence", "## Mitigation", "## Tokens"):
        assert heading in markdown
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    assert report["service"] == "inventory"
    assert report["kind"] == "latency"
    assert report["commit"] == truth["deployed_commit"]
    assert report["runbook"] == "rollback-latency"
    assert report["matched"] is True
    assert report["tokens"]["total"] == {"input": 0, "output": 0}
    assert truth["fault"] not in json.dumps(report)
    assert truth["marker"] not in json.dumps(report)
    for section in report["sections"].values():
        for claim in section:
            assert claim["text"] in markdown


def test_assemble_ignores_ground_truth(tmp_path):
    out = tmp_path / "run"
    run("bad_deploy", seed=2, requests=12, warmup=4, out=out)
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    (out / "ground_truth.json").write_text('{"fault": "latency_spike", "service": "gateway"}\n', encoding="utf-8")
    report = assemble(out)
    assert report["service"] == "payments"
    assert report["commit"] == truth["deployed_commit"]
    assert report["runbook"] == "revert-config"
    assert "latency_spike" not in json.dumps(evidence_digest(report))
    assert assemble(out) == report


def test_short_run_reports_no_incident(tmp_path):
    out = tmp_path / "run"
    run("latency_spike", seed=1, requests=4, warmup=1, out=out)
    report = assemble(out)
    assert report["incident"] is False
    assert report["sections"]["summary"] == [{"text": "No error-rate or latency spike found.", "citations": []}]
    assert report["steps"] == []
    assert check_report(report, out, tmp_path) == []


def test_example_report_matches_a_fresh_run(tmp_path):
    out = tmp_path / "run"
    report = respond("latency_spike", seed=1, requests=24, warmup=8, out=out)
    committed = json.loads((EXAMPLE / "rca.json").read_text(encoding="utf-8"))
    assert report == committed
    assert (EXAMPLE / "rca.md").read_text(encoding="utf-8") == render(report)
    assert report["tokens"] == {
        "forensics": {"input": 0, "output": 0},
        "archaeologist": {"input": 0, "output": 0},
        "runbook": {"input": 0, "output": 0},
        "orchestrator": {"input": 0, "output": 0},
        "total": {"input": 0, "output": 0},
    }


def test_cli_requires_a_fault():
    completed = subprocess.run(
        [sys.executable, "-m", "orchestrator"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_token_account_copies_measured_usage_and_fills_gaps():
    tokens = account(
        {"tokens": {"input": 3, "output": 4}},
        {},
        {"tokens": {"input": True, "output": -1}},
        {"input": 5, "output": 0},
    )
    assert tokens["forensics"] == {"input": 3, "output": 4}
    assert tokens["archaeologist"] == {"input": 0, "output": 0}
    assert tokens["runbook"] == {"input": 0, "output": 0}
    assert tokens["orchestrator"] == {"input": 5, "output": 0}
    assert tokens["total"] == {"input": 8, "output": 4}


def test_unknown_llm_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_LLM", "made-up")
    with pytest.raises(ValueError, match="unknown ORCHESTRATOR_LLM"):
        apply_prose(_blank())


def test_openai_without_a_key_is_rejected(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        apply_prose(_blank())


def test_default_provider_does_not_call_openai(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise AssertionError("openai was called")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = tmp_path / "run"
    run("latency_spike", seed=1, requests=12, warmup=4, out=out)
    report = assemble(out)
    assert report["tokens"]["orchestrator"] == {"input": 0, "output": 0}
    assert report["tokens"]["total"] == {"input": 0, "output": 0}


def _blank():
    zeros = {"input": 0, "output": 0}
    return {
        "sections": {},
        "tokens": {
            "forensics": zeros,
            "archaeologist": dict(zeros),
            "runbook": dict(zeros),
            "orchestrator": dict(zeros),
            "total": dict(zeros),
        },
    }
