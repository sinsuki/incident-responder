"""A claim with no citation, or a citation that does not resolve, is rejected."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from code_archaeologist.history import open_repo
from incident_sim.scenario import run
from orchestrator import assemble
from orchestrator.check import check_report
from orchestrator.llm import apply_prose

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    previous = os.environ.pop("ORCHESTRATOR_LLM", None)
    try:
        out = tmp_path_factory.mktemp("rca") / "run"
        run("error_rate_spike", seed=2, requests=16, warmup=6, out=out)
        (out / "ground_truth.json").unlink()
        report = assemble(out)
        return out, report
    finally:
        if previous is not None:
            os.environ["ORCHESTRATOR_LLM"] = previous


def test_real_report_citations_resolve(scenario):
    out, report = scenario
    checkout = open_repo(None)
    try:
        assert check_report(report, out, checkout.path) == []
    finally:
        checkout.close()
    assert report["runbook"] == "rollback-check"
    for claims in report["sections"].values():
        assert claims
        for claim in claims:
            assert claim["citations"]


def test_injected_hallucination_is_rejected(scenario, tmp_path):
    out, report = _copy(scenario)
    report["sections"]["summary"].append(
        {
            "text": "A regional cache failure caused the checkout errors.",
            "citations": [],
        }
    )
    problems, code, stderr = _verify(tmp_path, out, report)
    assert code == 1
    assert problems
    assert any("no citation" in problem for problem in problems)
    assert "no citation" in stderr


def test_unresolvable_commit_is_rejected(scenario, tmp_path):
    out, report = _copy(scenario)
    commit = "ab" * 20
    report["sections"]["root_cause"].append(
        {
            "text": f"Commit {commit} changed the connection pool at payments.py:1.",
            "citations": [
                {"commit": commit, "file": "payments.py", "line": 1, "text": "CONNECTION_POOL = 1"}
            ],
        }
    )
    problems, code, stderr = _verify(tmp_path, out, report)
    assert code == 1
    assert any("not in the history" in problem for problem in problems)
    assert "not in the history" in stderr


def test_sentence_that_names_an_unknown_timestamp_is_rejected(scenario):
    out, report = _copy(scenario)
    claim = report["sections"]["summary"][0]
    claim["text"] = claim["text"] + " The cache expired at 1111111111111111111."
    checkout = open_repo(None)
    try:
        problems = check_report(report, out, checkout.path)
    finally:
        checkout.close()
    assert any("1111111111111111111" in problem for problem in problems)
    assert any("no citation" in problem for problem in problems)


def test_polished_hallucination_is_rechecked(monkeypatch, scenario, tmp_path):
    out, report = _copy(scenario)
    monkeypatch.setenv("ORCHESTRATOR_LLM", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def fake(request, timeout=60):
        sent = json.loads(request.data.decode("utf-8"))
        digest = json.loads(sent["messages"][1]["content"])
        digest["sections"]["summary"] = list(digest["sections"]["summary"])
        digest["sections"]["summary"].append("A regional cache failure caused the checkout errors.")
        body = {
            "choices": [{"message": {"content": json.dumps(digest)}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 4},
        }
        return _Response(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake)
    polished = apply_prose(report)
    assert polished["tokens"]["orchestrator"] == {"input": 15, "output": 4}
    assert polished["tokens"]["forensics"] == {"input": 0, "output": 0}
    assert polished["tokens"]["total"] == {"input": 15, "output": 4}
    _problems, code, stderr = _verify(tmp_path, out, polished)
    assert code == 1
    assert "no citation" in stderr


def test_verify_missing_run_exits_2(tmp_path):
    path = tmp_path / "rca.json"
    path.write_text("{}\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "orchestrator.verify", str(path), "--run", str(tmp_path / "missing")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2


def _verify(tmp_path: Path, out: Path, report: dict) -> tuple[list[str], int, str]:
    path = tmp_path / "rca.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "orchestrator.verify", str(path), "--run", str(out)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    checkout = open_repo(None)
    try:
        problems = check_report(report, out, checkout.path)
    finally:
        checkout.close()
    return problems, completed.returncode, completed.stderr


def _copy(scenario):
    out, report = scenario
    return out, json.loads(json.dumps(report))


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload
