"""Applying the steps in the simulator clears the fault. Raising the timeout does not."""

import json
import subprocess

import pytest

from code_archaeologist import investigate as rank
from incident_sim.faults import FAULTS
from incident_sim.history import clone
from incident_sim.scenario import run
from log_forensics import investigate as read_incident
from runbook import recommend
from runbook.apply import patch, replay
from runbook.check import check_citations

EXPECTED = {
    "latency_spike": ("rollback-latency", ["rollback"]),
    "error_rate_spike": ("rollback-check", ["rollback"]),
    "dependency_timeout": ("rollback-timeout", ["rollback", "raise_timeout"]),
    "bad_deploy": ("revert-config", ["revert_config"]),
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_procedure_clears_the_fault(tmp_path, fault):
    truth, forensics, archaeology, report = _case(tmp_path, fault)
    runbook, actions = EXPECTED[fault]
    assert report["matched"] is True
    assert report["runbook"] == runbook
    assert [step["action"] for step in report["steps"]] == actions
    assert report["commit"] == truth["deployed_commit"]
    assert report["tokens"] == {"input": 0, "output": 0}
    assert "planted" not in json.dumps(report)
    assert check_citations(report, forensics, archaeology) == []
    step = report["steps"][0]
    assert step["target"]["commit"] in step["text"]
    timestamp = next(item["timestamp_unix_nano"] for item in step["citations"] if item["type"] == "forensics")
    assert str(timestamp) in step["text"]

    out = tmp_path / "mitigated"
    replay(report["steps"], seed=1, requests=16, warmup=6, out=out)
    after = read_incident(out)
    assert after["incident"] is False
    assert after["claims"] == []
    assert not (out / "ground_truth.json").exists()


def test_raising_the_timeout_alone_leaves_a_latency_spike(tmp_path):
    _truth, _forensics, _archaeology, report = _case(tmp_path, "dependency_timeout")
    rollback = report["steps"][0]
    raised = report["steps"][1]
    target = dict(raised["target"])
    target["parent"] = rollback["target"]["parent"]
    out = tmp_path / "mitigated"
    replay([{"action": "raise_timeout", "target": target}], seed=1, requests=16, warmup=6, out=out)
    after = read_incident(out)
    assert after["incident"] is True
    assert after["service"] == "payments"
    assert after["kind"] == "latency"


def test_rollback_alone_clears_the_timeout(tmp_path):
    _truth, _forensics, _archaeology, report = _case(tmp_path, "dependency_timeout")
    out = tmp_path / "mitigated"
    replay([report["steps"][0]], seed=1, requests=16, warmup=6, out=out)
    after = read_incident(out)
    assert after["incident"] is False


def test_revert_edits_only_the_named_constant(tmp_path):
    _truth, _forensics, _archaeology, report = _case(tmp_path, "bad_deploy")
    repo = tmp_path / "repo"
    clone(repo)
    commit = report["steps"][0]["target"]["commit"]
    subprocess.run(["git", "checkout", "--quiet", "--detach", commit], cwd=repo, check=True)
    before = (repo / "payments.py").read_text(encoding="utf-8").splitlines()
    patch(repo, report["steps"])
    after = (repo / "payments.py").read_text(encoding="utf-8").splitlines()
    changed = [(old, new) for old, new in zip(before, after) if old != new]
    assert changed == [("CURRENCY_SCALE = 100", "CURRENCY_SCALE = 1")]
    assert len(before) == len(after)
    assert "def format_receipt" in "\n".join(after)


def test_patch_rejects_a_bad_hash(tmp_path):
    repo = tmp_path / "repo"
    clone(repo)
    step = {
        "action": "rollback",
        "target": {"commit": "HEAD", "parent": "HEAD", "file": "inventory.py"},
    }
    with pytest.raises(ValueError, match="hash"):
        patch(repo, [step])


def _case(tmp_path, fault):
    out = tmp_path / "run"
    run(fault, seed=1, requests=16, warmup=6, out=out)
    truth = json.loads((out / "ground_truth.json").read_text(encoding="utf-8"))
    (out / "ground_truth.json").unlink()
    forensics = read_incident(out)
    archaeology = rank(forensics)
    planted = dict(forensics)
    planted["fault"] = "planted"
    planted["deployed_commit"] = "c" * 40
    report = recommend(planted, archaeology)
    return truth, planted, archaeology, report
