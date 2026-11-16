"""Citations have to name a commit and a line that exist there."""

import pytest

from code_archaeologist import investigate
from code_archaeologist.check import check_citations
from code_archaeologist.history import open_repo
from incident_sim.scenario import run
from log_forensics import investigate as read_incident


@pytest.fixture
def cited(tmp_path):
    out = tmp_path / "run"
    run("dependency_timeout", seed=2, requests=16, warmup=6, out=out)
    report = investigate(read_incident(out))
    checkout = open_repo()
    try:
        yield report, checkout.path
    finally:
        checkout.close()


def test_real_report_citations_resolve(cited):
    report, repo = cited
    assert check_citations(report, repo) == []
    assert report["commit"] in report["claims"][0]["text"]


def test_unknown_commit_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["commit"] = "a" * 40
    problems = check_citations(report, repo)
    assert any("not in the history" in problem for problem in problems)


def test_short_hash_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["commit"] = report["commit"][:12]
    problems = check_citations(report, repo)
    assert any("not a full hash" in problem for problem in problems)


def test_line_past_the_end_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["line"] = 10_000
    problems = check_citations(report, repo)
    assert any("past the end" in problem for problem in problems)


def test_wrong_line_text_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["text"] = "WORK_MS = 1"
    problems = check_citations(report, repo)
    assert any("text does not match" in problem for problem in problems)


def test_missing_file_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["file"] = "missing.py"
    problems = check_citations(report, repo)
    assert any("not in" in problem for problem in problems)


def test_parent_path_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["file"] = "../payments.py"
    problems = check_citations(report, repo)
    assert any("not a path" in problem for problem in problems)


def test_claim_without_citations_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"] = []
    problems = check_citations(report, repo)
    assert any("no citations" in problem for problem in problems)


def test_named_commit_without_claims_does_not_resolve(cited):
    report, repo = cited
    report["claims"] = []
    problems = check_citations(report, repo)
    assert any("no claims" in problem for problem in problems)


def test_line_zero_does_not_resolve(cited):
    report, repo = cited
    report["claims"][0]["citations"][0]["line"] = 0
    problems = check_citations(report, repo)
    assert any("positive integer" in problem for problem in problems)


def test_ranked_line_must_exist(cited):
    report, repo = cited
    report["ranked"][0]["text"] = "not the line"
    problems = check_citations(report, repo)
    assert any("ranked 0" in problem for problem in problems)
