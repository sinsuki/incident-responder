"""The bundle, the manifest, and a fresh build agree."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from incident_sim.checkout import AMOUNT_CENTS
from incident_sim.faults import FAULTS
from incident_sim.history import BUNDLE, MANIFEST, clone, fault_commit, load_revision, manifest

ROOT = Path(__file__).resolve().parents[1]


def test_bundle_matches_manifest(tmp_path):
    repo = tmp_path / "repo"
    clone(repo)
    rows = manifest()
    hashes = subprocess.check_output(
        ["git", "rev-list", "--reverse", "--all"],
        cwd=repo,
        text=True,
    ).split()
    assert set(hashes) == {row["hash"] for row in rows}
    branches = subprocess.check_output(["git", "branch", "-a"], cwd=repo, text=True)
    roots = [row for row in rows if row["parent"] is None]
    assert len(roots) == 1
    assert roots[0]["fault"] is None
    for row in rows:
        assert row["branch"] in branches
        if row["parent"] is None:
            continue
        parent = subprocess.check_output(["git", "rev-parse", f"{row['hash']}^"], cwd=repo, text=True).strip()
        assert parent == row["parent"]
        if row["fault"] is not None:
            assert FAULTS[row["fault"]].name == row["fault"]


def test_rebuild_matches_committed_manifest(tmp_path):
    bundle = tmp_path / "shop.bundle"
    rebuilt_manifest = tmp_path / "commits.json"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "sample_history" / "build_repo.py"),
            "--repo",
            str(tmp_path / "repo"),
            "--bundle",
            str(bundle),
            "--manifest",
            str(rebuilt_manifest),
        ],
        check=True,
    )
    assert json.loads(rebuilt_manifest.read_text(encoding="utf-8")) == json.loads(
        MANIFEST.read_text(encoding="utf-8")
    )
    assert bundle.stat().st_size > 0
    assert BUNDLE.stat().st_size > 0


def test_fault_commit_differs_from_its_parent(tmp_path):
    repo = tmp_path / "repo"
    clone(repo)
    for name, spec in FAULTS.items():
        row = fault_commit(name)
        parent = load_revision(repo, row["parent"])
        deployed = load_revision(repo, row["hash"])
        if name == "latency_spike":
            assert parent.inventory.WORK_MS == 12
            assert deployed.inventory.WORK_MS == 750
            deployed.inventory.reserve("sku-1", 1)
        elif name == "error_rate_spike":
            assert parent.payments.charge(AMOUNT_CENTS, "00")["approved"] is True
            with pytest.raises(RuntimeError, match="processor code 00"):
                deployed.payments.charge(AMOUNT_CENTS, "00")
            assert deployed.payments.charge(AMOUNT_CENTS, "91")["approved"] is True
        elif name == "dependency_timeout":
            assert parent.payments.WORK_MS < parent.orders.PAYMENTS_TIMEOUT_MS
            assert deployed.payments.WORK_MS > deployed.orders.PAYMENTS_TIMEOUT_MS
        elif name == "bad_deploy":
            parent.payments.charge(AMOUNT_CENTS, "00")
            with pytest.raises(ValueError, match="amount out of range: 800000"):
                deployed.payments.charge(AMOUNT_CENTS, "00")
        else:
            raise AssertionError(name)
        source = (ROOT / "sample_history" / "trees" / row["tree"] / spec.path).read_text(encoding="utf-8")
        assert any(line.strip() == spec.marker for line in source.splitlines())


def test_history_has_distractors_on_the_fault_files(tmp_path):
    """A fault commit is not the only edit to its file, and its subject does not name the fault."""
    repo = tmp_path / "repo"
    clone(repo)
    rows = manifest()
    main_tip = [row for row in rows if row["branch"] == "main"][-1]
    giveaways = ("invert", "rebuild", "stuck", "scale", "latency", "timeout")
    for name, spec in FAULTS.items():
        row = fault_commit(name)
        assert row["parent"] == main_tip["hash"]
        subject = row["subject"].lower()
        assert name.replace("_", " ") not in subject
        assert not any(word in subject for word in giveaways)
        touched = subprocess.check_output(
            ["git", "log", "--all", "--pretty=%H", "--", spec.path],
            cwd=repo,
            text=True,
        ).split()
        assert row["hash"] in touched
        assert len(touched) >= 4
        children = [other for other in rows if other["parent"] == row["hash"]]
        assert len(children) == 1
        child = children[0]
        assert child["fault"] is None
        blamed = _blame_marker(repo, child["hash"], spec.path, spec.marker)
        assert blamed == row["hash"]


def _blame_marker(repo, commit, path, marker) -> str:
    source = subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=repo, text=True)
    lines = [index + 1 for index, line in enumerate(source.splitlines()) if line.strip() == marker]
    assert len(lines) == 1
    porcelain = subprocess.check_output(
        ["git", "blame", "-L", f"{lines[0]},{lines[0]}", "--porcelain", commit, "--", path],
        cwd=repo,
        text=True,
    )
    return porcelain.splitlines()[0].split()[0]
