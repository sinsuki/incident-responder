"""Citations have to name a runbook section and an upstream claim."""

import copy
import os

import pytest

from code_archaeologist import investigate as rank
from incident_sim.scenario import run
from log_forensics import investigate as read_incident
from runbook import recommend
from runbook.check import check_citations


@pytest.fixture(scope="module")
def cited(tmp_path_factory):
    previous = os.environ.pop("RUNBOOK_LLM", None)
    try:
        out = tmp_path_factory.mktemp("cited") / "run"
        run("error_rate_spike", seed=2, requests=16, warmup=6, out=out)
        (out / "ground_truth.json").unlink()
        forensics = read_incident(out)
        archaeology = rank(forensics)
        report = recommend(forensics, archaeology)
        return forensics, archaeology, report
    finally:
        if previous is not None:
            os.environ["RUNBOOK_LLM"] = previous


def test_real_report_citations_resolve(cited):
    forensics, archaeology, report = cited
    assert report["runbook"] == "rollback-check"
    assert check_citations(report, forensics, archaeology) == []
    step = report["steps"][0]
    assert step["target"]["commit"] in step["text"]
    assert step["target"]["parent"] in step["text"]
    timestamp = next(item["timestamp_unix_nano"] for item in step["citations"] if item["type"] == "forensics")
    assert str(timestamp) in step["text"]
    assert recommend(forensics, archaeology) == report


def test_unknown_section_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"][0]["section"] = "Not a section"
    report["steps"][0]["citations"][0]["section"] = "Not a section"
    problems = check_citations(report, forensics, archaeology)
    assert any("is not in" in problem for problem in problems)


def test_wrong_runbook_file_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"][0]["citations"][0]["file"] = "shed-load.md"
    problems = check_citations(report, forensics, archaeology)
    assert any("does not match the selected runbook" in problem for problem in problems)


def test_timestamp_not_in_the_claim_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    for citation in report["steps"][0]["citations"]:
        if citation["type"] == "forensics":
            citation["timestamp_unix_nano"] = 1
    problems = check_citations(report, forensics, archaeology)
    assert any("timestamp is not in that forensics claim" in problem for problem in problems)


def test_commit_not_in_the_claim_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    for citation in report["steps"][0]["citations"]:
        if citation["type"] == "archaeologist" and citation["commit"] == report["commit"]:
            citation["commit"] = "d" * 40
    problems = check_citations(report, forensics, archaeology)
    assert any("commit is not in that archaeologist claim" in problem for problem in problems)


def test_claim_index_out_of_range_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    for citation in report["steps"][0]["citations"]:
        if citation["type"] == "forensics":
            citation["claim"] = 99
    problems = check_citations(report, forensics, archaeology)
    assert any("claim is out of range" in problem for problem in problems)


def test_missing_parent_citation_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"][0]["citations"] = [
        item for item in report["steps"][0]["citations"] if item.get("commit") != report["steps"][0]["target"]["parent"]
    ]
    problems = check_citations(report, forensics, archaeology)
    assert any("parent commit is not cited" in problem for problem in problems)


def test_step_without_evidence_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"][0]["citations"] = [report["steps"][0]["citations"][0]]
    problems = check_citations(report, forensics, archaeology)
    assert any("no evidence citation" in problem for problem in problems)


def test_matched_report_without_steps_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"] = []
    problems = check_citations(report, forensics, archaeology)
    assert problems == ["matched report has no steps"]


def test_empty_step_text_does_not_resolve(cited):
    forensics, archaeology, report = _copy(cited)
    report["steps"][0]["text"] = "  "
    problems = check_citations(report, forensics, archaeology)
    assert any("no text" in problem for problem in problems)


def _copy(cited):
    forensics, archaeology, report = cited
    return forensics, archaeology, copy.deepcopy(report)
