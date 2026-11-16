"""Load service modules from the sample git bundle."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "sample_history" / "shop.bundle"
MANIFEST = ROOT / "sample_history" / "commits.json"


@dataclass(frozen=True)
class Revision:
    commit: str
    gateway: ModuleType
    orders: ModuleType
    payments: ModuleType
    inventory: ModuleType


def manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def fault_commit(fault: str) -> dict:
    for row in manifest():
        if row["fault"] == fault:
            return row
    raise KeyError(fault)


def clone(dest: Path) -> None:
    subprocess.run(
        ["git", "clone", "--quiet", str(BUNDLE), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )


def load_revision(repo: Path, commit: str) -> Revision:
    subprocess.run(
        ["git", "checkout", "--quiet", "--detach", commit],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    prefix = commit[:12]
    return Revision(
        commit=commit,
        gateway=_load(repo / "gateway.py", f"gateway_{prefix}"),
        orders=_load(repo / "orders.py", f"orders_{prefix}"),
        payments=_load(repo / "payments.py", f"payments_{prefix}"),
        inventory=_load(repo / "inventory.py", f"inventory_{prefix}"),
    )


def _load(path: Path, name: str) -> ModuleType:
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
