"""Top-1 is an exact commit match. Top-3 allows the two commits under it."""

from code_archaeologist.eval import score_case


def test_exact_top_commit_scores_one():
    report = _report("a" * 40, ["a" * 40, "b" * 40, "c" * 40])
    scored = score_case(report, {"deployed_commit": "a" * 40})
    assert scored["top1"] is True
    assert scored["top3"] is True
    assert scored["score"] == 1
    assert scored["passed"] is True
    assert scored["input_tokens"] == 0
    assert scored["output_tokens"] == 0


def test_third_place_counts_as_top3_only():
    report = _report("b" * 40, ["b" * 40, "c" * 40, "a" * 40])
    scored = score_case(report, {"deployed_commit": "a" * 40})
    assert scored["top1"] is False
    assert scored["top3"] is True
    assert scored["score"] == 0
    assert scored["passed"] is False


def test_fourth_place_is_a_miss():
    report = _report("b" * 40, ["b" * 40, "c" * 40, "d" * 40, "a" * 40])
    scored = score_case(report, {"deployed_commit": "a" * 40})
    assert scored["top1"] is False
    assert scored["top3"] is False
    assert scored["score"] == 0


def test_no_commit_scores_zero():
    report = {
        "commit": None,
        "ranked": [],
        "tokens": {"input": 0, "output": 0},
    }
    scored = score_case(report, {"deployed_commit": "a" * 40})
    assert scored["top1"] is False
    assert scored["top3"] is False
    assert scored["predicted"] is None
    assert scored["score"] == 0
    assert scored["passed"] is False


def _report(top, ranked):
    return {
        "commit": top,
        "ranked": [{"commit": commit} for commit in ranked],
        "tokens": {"input": 0, "output": 0},
    }
