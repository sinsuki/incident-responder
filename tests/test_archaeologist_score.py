"""Diff scoring uses the source text, not the commit subject."""

import os
import subprocess
from pathlib import Path

from code_archaeologist.load import Profile
from code_archaeologist.rank import rank_commits
from code_archaeologist.score import score_pair

ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "sample_history" / "trees"

AMOUNT = "charge failed: amount out of range: 800000"
PROCESSOR = "charge failed: processor code 00"


def test_duration_match_beats_a_small_timing_change():
    tip = _text("10-payments-timing/payments.py")
    receipt = _text("09-receipt/payments.py")
    timeout = _text("03-timeout/payments.py")
    profile = _profile("payments", "timeout", 48, 2000, "payments timed out after 800ms", 800)
    hit = score_pair(profile, tip, timeout)
    tweak = score_pair(profile, receipt, tip)
    assert hit is not None and tweak is not None
    assert hit.score == 1
    assert hit.line_text == "WORK_MS = 2000"
    assert tweak.score < 0.2
    assert tweak.line_text == "WORK_MS = 48"


def test_latency_match_beats_a_later_catalog_edit():
    parent = _text("10-payments-timing/inventory.py")
    fault = _text("01-latency/inventory.py")
    later = _text("11-latency-extra/inventory.py")
    profile = _profile("inventory", "latency", 12, 750, None, None)
    hit = score_pair(profile, parent, fault)
    extra = score_pair(profile, fault, later)
    assert hit is not None and extra is not None
    assert hit.score == 1
    assert hit.line_text == "WORK_MS = 750"
    assert extra.score < hit.score
    assert "WORK_MS" not in extra.line_text


def test_scale_change_explains_the_amount_error_and_the_inversion_does_not():
    tip = _text("10-payments-timing/payments.py")
    scaled = _text("04-bad-deploy/payments.py")
    inverted = _text("02-error-rate/payments.py")
    profile = _profile("payments", "error_rate", 48, 48, AMOUNT, None)
    hit = score_pair(profile, tip, scaled)
    other = score_pair(profile, tip, inverted)
    assert hit is not None and other is not None
    assert hit.score == 0.95
    assert hit.label == "constant"
    assert hit.line_text == "CURRENCY_SCALE = 100"
    assert "8000" in hit.detail
    assert other.score < 0.5


def test_inverted_check_explains_processor_code_and_the_scale_change_does_not():
    tip = _text("10-payments-timing/payments.py")
    scaled = _text("04-bad-deploy/payments.py")
    inverted = _text("02-error-rate/payments.py")
    profile = _profile("payments", "error_rate", 48, 48, PROCESSOR, None)
    hit = score_pair(profile, tip, inverted)
    other = score_pair(profile, tip, scaled)
    assert hit is not None and other is not None
    assert hit.score == 0.9
    assert hit.label == "predicate"
    assert hit.line_text == "if response_code not in RETRYABLE:"
    assert other.score < 0.5


def test_comment_only_change_is_not_scored():
    profile = _profile("inventory", "latency", 12, 750, None, None)
    assert score_pair(profile, "WORK_MS = 12\n", "WORK_MS = 12\n# note\n") is None


def test_misleading_subject_does_not_outrank_the_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, ["init", "-b", "main"])
    _commit(repo, "inventory.py", "WORK_MS = 12\n", "add inventory", "2026-01-08T10:00:00+00:00")
    _commit(
        repo,
        "inventory.py",
        "WORK_MS = 12\n\ndef rebuild_index():\n    return None\n",
        "rebuild the inventory index on each reserve",
        "2026-01-08T11:00:00+00:00",
    )
    _commit(
        repo,
        "inventory.py",
        "WORK_MS = 750\n\ndef rebuild_index():\n    return None\n",
        "note a catalog size",
        "2026-01-08T12:00:00+00:00",
    )
    subjects = _subjects(repo)
    ranked = rank_commits(_profile("inventory", "latency", 12, 750, None, None), repo)
    assert ranked[0].commit == subjects["note a catalog size"]
    assert ranked[0].line_text == "WORK_MS = 750"
    assert ranked[0].score > ranked[1].score
    assert subjects["rebuild the inventory index on each reserve"] != ranked[0].commit


def _text(name: str) -> str:
    return (TREES / name).read_text(encoding="utf-8")


def _profile(service, kind, baseline, incident, signature, timeout_ms) -> Profile:
    return Profile(True, service, kind, 1, baseline, incident, signature, timeout_ms)


def _git(repo: Path, args: list[str], message: str | None = None, when: str | None = None) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Shop Dev"
    env["GIT_AUTHOR_EMAIL"] = "dev@shop.example"
    env["GIT_COMMITTER_NAME"] = "Shop Dev"
    env["GIT_COMMITTER_EMAIL"] = "dev@shop.example"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", *args], cwd=repo, env=env, input=message, text=True, check=True, capture_output=True)


def _commit(repo: Path, filename: str, text: str, subject: str, when: str) -> None:
    (repo / filename).write_text(text, encoding="utf-8")
    _git(repo, ["add", filename], when=when)
    _git(repo, ["commit", "--cleanup=verbatim", "--no-gpg-sign", "-F", "-"], subject + "\n", when)


def _subjects(repo: Path) -> dict[str, str]:
    text = subprocess.check_output(["git", "log", "--pretty=%H %s"], cwd=repo, text=True)
    found = {}
    for line in text.splitlines():
        sha, subject = line.split(" ", 1)
        found[subject] = sha
    return found
