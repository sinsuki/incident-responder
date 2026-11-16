"""Apply runbook steps to a checkout and replay the checkout path.

The warmup window runs the parent commit named by the steps. The rest run
the implicated commit after the steps have edited it. Log forensics can
then be run on the result. This module does not write ground truth.
"""

from __future__ import annotations

import importlib.util
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from incident_sim.checkout import response_code, run_checkout
from incident_sim.clock import GAP_NS, START_NS
from incident_sim.history import Revision, clone, load_revision
from incident_sim.telemetry import Session

_FILES = {"gateway.py", "orders.py", "inventory.py", "payments.py"}
_HASH = re.compile(r"^[0-9a-f]{40}$")
_NAME = re.compile(r"[A-Z][A-Z0-9_]*")
_seq = 0


def replay(steps: list[dict], seed: int, requests: int, warmup: int, out: Path | str) -> None:
    """Write telemetry for the patched services. `out` is the directory."""
    if requests < 1:
        raise ValueError("requests must be >= 1")
    if not 0 <= warmup < requests:
        raise ValueError("warmup must be >= 0 and less than requests")
    commit, parent = _anchors(steps)
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        clone(repo)
        parent_rev = load_revision(repo, parent)
        _git(repo, ["checkout", "--quiet", "--detach", commit])
        patch(repo, steps)
        patched = _working_revision(repo)
        _require(patched)
        _write_run(parent_rev, patched, seed, requests, warmup, out)


def patch(repo: Path, steps: list[dict]) -> None:
    """Apply `steps` to a checkout that is already at the implicated commit."""
    for step in steps:
        _apply_one(Path(repo), step)


def _apply_one(repo: Path, step: dict) -> None:
    if not isinstance(step, dict):
        raise ValueError("step is not an object")
    action = step.get("action")
    target = step.get("target")
    if not isinstance(target, dict):
        raise ValueError("step has no target")
    if action == "shed_load":
        return
    if action == "rollback":
        filename = _file(target.get("file"))
        parent = _hash(target.get("parent"), "parent")
        _git(repo, ["checkout", "--quiet", parent, "--", filename])
        return
    if action in {"revert_config", "raise_timeout"}:
        filename = _file(target.get("file"))
        _set_constant(repo / filename, _constant(target.get("constant")), _whole(target.get("value")))
        return
    raise ValueError(f"unknown action {action}")


def _anchors(steps: list[dict]) -> tuple[str, str]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps do not name a commit to patch")
    commits = []
    parents = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("target"), dict):
            raise ValueError("step has no target")
        target = step["target"]
        if target.get("commit"):
            commits.append(_hash(target["commit"], "commit"))
        if target.get("parent"):
            parents.append(_hash(target["parent"], "parent"))
    if len(set(commits)) != 1:
        raise ValueError("steps do not name one commit")
    if len(set(parents)) != 1:
        raise ValueError("steps do not name one parent")
    return commits[0], parents[0]


def _write_run(parent: Revision, patched: Revision, seed: int, requests: int, warmup: int, out: Path) -> None:
    # No ground_truth.json. The re-run is evidence the patch is healthy,
    # and forensics must not have a planted answer beside the telemetry.
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    clock = START_NS
    last_end = START_NS
    with Session(out, seed) as session:
        for index in range(requests):
            if index == warmup and warmup > 0:
                session.collect(last_end)
            active = parent if index < warmup else patched
            code = response_code(rng)
            last_end = run_checkout(session, active, index, code, clock)
            clock = last_end + GAP_NS
        session.collect(last_end)


def _working_revision(repo: Path) -> Revision:
    global _seq
    _seq += 1
    tag = f"patched{_seq}"
    return Revision(
        commit=tag,
        gateway=_load(repo / "gateway.py", f"gateway_{tag}"),
        orders=_load(repo / "orders.py", f"orders_{tag}"),
        payments=_load(repo / "payments.py", f"payments_{tag}"),
        inventory=_load(repo / "inventory.py", f"inventory_{tag}"),
    )


def _require(revision: Revision) -> None:
    _int_attr(revision.inventory, "WORK_MS")
    _int_attr(revision.payments, "WORK_MS")
    _int_attr(revision.orders, "PAYMENTS_TIMEOUT_MS")


def _int_attr(module, name: str) -> None:
    value = getattr(module, name, None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{module.__name__} is missing {name}")


def _set_constant(path: Path, name: str, value: int) -> None:
    if not path.is_file():
        raise ValueError(f"{path.name} is not in the checkout")
    pattern = re.compile(rf"^{re.escape(name)} = \d+\s*$")
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    found = []
    for index, line in enumerate(lines):
        if pattern.match(line):
            found.append(index)
    if len(found) != 1:
        raise ValueError(f"{path.name} has {len(found)} assignments to {name}")
    index = found[0]
    newline = "\n" if lines[index].endswith("\n") else ""
    lines[index] = f"{name} = {value}{newline}"
    path.write_text("".join(lines), encoding="utf-8")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _git(repo: Path, args: list[str]) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed\n{detail}")


def _hash(value, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{label} is not a full hash")
    return value


def _file(value) -> str:
    if value not in _FILES:
        raise ValueError(f"file is not a service module: {value}")
    return value


def _constant(value) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"constant is not a name: {value}")
    return value


def _whole(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"value is not a whole number: {value}")
    return value
