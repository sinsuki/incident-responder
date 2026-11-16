"""Same seed, same files. A different seed changes the trace ids."""

from incident_sim.scenario import run


def test_same_seed_is_byte_identical(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    run("dependency_timeout", seed=5, requests=12, warmup=4, out=first)
    run("dependency_timeout", seed=5, requests=12, warmup=4, out=second)
    for name in ("traces.jsonl", "logs.jsonl", "metrics.jsonl", "ground_truth.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_seed_changes_trace_ids(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    run("latency_spike", seed=1, requests=4, warmup=1, out=first)
    run("latency_spike", seed=2, requests=4, warmup=1, out=second)
    assert (first / "traces.jsonl").read_bytes() != (second / "traces.jsonl").read_bytes()
