"""The runbook agent picks a cited procedure and does not call a model by default."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from code_archaeologist import investigate as rank
from incident_sim.scenario import run
from log_forensics import investigate as read_incident
from runbook import recommend
from runbook.books import default_directory, load_runbooks
from runbook.check import check_citations
from runbook.llm import apply_summary, evidence_digest

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_shapes_do_not_overlap():
    books = load_runbooks(default_directory())
    shapes = [(book.kind, book.line) for book in books]
    assert len(shapes) == len(set(shapes)) == 6
    assert {book.id for book in books} == {book.path.stem for book in books}
    assert {book.id for book in books} == {
        "raise-timeout",
        "revert-config",
        "rollback-check",
        "rollback-latency",
        "rollback-timeout",
        "shed-load",
    }


def test_no_incident_has_no_steps():
    report = recommend({"incident": False}, {})
    assert report["incident"] is False
    assert report["matched"] is False
    assert report["steps"] == []
    assert report["runbook"] is None
    assert report["tokens"] == {"input": 0, "output": 0}
    assert report["summary"] == "No incident to mitigate."


def test_cli_writes_a_cited_report(tmp_path):
    out = tmp_path / "run"
    report_path = tmp_path / "report.json"
    run("latency_spike", seed=1, requests=16, warmup=6, out=out)
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    (out / "ground_truth.json").write_text('{"service": "gateway"}\n', encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "runbook", str(out), "--out", str(report_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert json.loads(completed.stdout) == report
    assert report["runbook"] == "rollback-latency"
    assert report["matched"] is True
    assert report["commit"] == truth["deployed_commit"]
    assert report["tokens"] == {"input": 0, "output": 0}
    assert [step["action"] for step in report["steps"]] == ["rollback"]
    assert truth["deployed_commit"] in report["steps"][0]["text"]
    forensics = read_incident(out)
    archaeology = rank(forensics)
    assert check_citations(report, forensics, archaeology) == []


def test_cli_reads_two_saved_reports(tmp_path):
    out = tmp_path / "run"
    run("bad_deploy", seed=2, requests=16, warmup=6, out=out)
    (out / "ground_truth.json").unlink()
    forensics = read_incident(out)
    archaeology = rank(forensics)
    forensics_path = tmp_path / "forensics.json"
    archaeology_path = tmp_path / "archaeology.json"
    report_path = tmp_path / "report.json"
    forensics_path.write_text(json.dumps(forensics), encoding="utf-8")
    archaeology_path.write_text(json.dumps(archaeology), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "runbook",
            str(forensics_path),
            str(archaeology_path),
            "--out",
            str(report_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runbook"] == "revert-config"
    assert report["steps"][0]["target"]["constant"] == "CURRENCY_SCALE"
    assert report["steps"][0]["target"]["value"] == 1
    assert report == recommend(forensics, archaeology)


def test_cli_file_without_archaeology_exits_2(tmp_path):
    path = tmp_path / "forensics.json"
    path.write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "runbook", str(path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert "required" in completed.stderr


def test_cli_missing_directory_exits_2(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "runbook", str(tmp_path / "missing")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_cli_rejects_a_non_object(tmp_path):
    forensics = tmp_path / "forensics.json"
    archaeology = tmp_path / "archaeology.json"
    forensics.write_text("[]\n", encoding="utf-8")
    archaeology.write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "runbook", str(forensics), str(archaeology)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def test_unknown_llm_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("RUNBOOK_LLM", "made-up")
    with pytest.raises(ValueError, match="unknown RUNBOOK_LLM"):
        apply_summary(_blank())


def test_openai_without_a_key_is_rejected(monkeypatch):
    monkeypatch.setenv("RUNBOOK_LLM", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        apply_summary(_blank())


def test_default_provider_does_not_call_openai(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("openai was called")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    report = recommend({"incident": False}, {})
    assert report["tokens"] == {"input": 0, "output": 0}


def test_digest_leaves_out_the_runbook_prose_and_the_source(tmp_path):
    out = tmp_path / "run"
    run("latency_spike", seed=1, requests=12, warmup=4, out=out)
    forensics = read_incident(out)
    forensics["fault"] = "latency_spike"
    forensics["deployed_commit"] = "c" * 40
    archaeology = rank(forensics)
    archaeology["summary"] = "update inventory reservation path"
    report = recommend(forensics, archaeology)
    assert report["runbook"] == "rollback-latency"
    assert "latency_spike" not in json.dumps(report)
    assert "update inventory reservation path" not in json.dumps(report)
    digest = evidence_digest(report)
    encoded = json.dumps(digest)
    assert set(digest) == {
        "commit",
        "incident",
        "kind",
        "matched",
        "onset_timestamp",
        "runbook",
        "service",
        "started_at_unix_nano",
        "steps",
    }
    assert "def reserve" not in encoded
    assert "_rebuild_catalog_index" not in encoded
    assert "update inventory reservation path" not in encoded
    assert "ground_truth" not in encoded
    assert "latency_spike" not in encoded
    assert len(encoded) < 4000
    assert recommend(forensics, archaeology) == report


def _blank():
    return {
        "commit": None,
        "incident": False,
        "kind": None,
        "matched": False,
        "runbook": None,
        "service": None,
        "started_at_unix_nano": None,
        "steps": [],
        "summary": "No incident to mitigate.",
        "tokens": {"input": 0, "output": 0},
    }
