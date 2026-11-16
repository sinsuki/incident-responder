"""Read the sample service history. This module does not score commits.

`commits_touching` returns hashes and parents only. Commit subjects are not
loaded, so a later step cannot rank on a message that names a fault.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from incident_sim.history import BUNDLE

_HASH = re.compile(r"^[0-9a-f]{40}$")
# Hash and parents. %s (the subject) is intentionally absent.
_PRETTY = "%H%x09%P"


@dataclass
class Checkout:
    path: Path
    _tmp: tempfile.TemporaryDirectory | None = None

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None


def open_repo(history: Path | None = None) -> Checkout:
    """Clone the sample bundle, or use `history` when it is a repo or a bundle."""
    if history is None:
        history = BUNDLE
    history = Path(history)
    if history.is_dir() and (history / ".git").exists():
        return Checkout(history)
    if history.is_file():
        tmp = tempfile.TemporaryDirectory()
        dest = Path(tmp.name) / "repo"
        _run(["clone", "--quiet", str(history), str(dest)])
        return Checkout(dest, tmp)
    raise FileNotFoundError(f"history not found: {history}")


def commits_touching(repo: Path, path: str) -> list[tuple[str, str | None]]:
    """Commits that change `path`, as `(hash, parent or None)`."""
    result = _run(["log", "--all", f"--pretty=format:{_PRETTY}", "--", path], cwd=repo)
    found: dict[str, str | None] = {}
    for line in result.splitlines():
        if not line.strip():
            continue
        sha, _, parent_field = line.partition("\t")
        if not _HASH.fullmatch(sha) or sha in found:
            continue
        parent = parent_field.split()[0] if parent_field.strip() else None
        if parent is not None and not _HASH.fullmatch(parent):
            parent = None
        found[sha] = parent
    return list(found.items())


def file_at(repo: Path, commit: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "cat-file", "-p", f"{commit}:{path}"],
        cwd=repo,
        env=_env(),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def is_commit(repo: Path, sha: str) -> bool:
    if not _HASH.fullmatch(sha):
        return False
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=repo,
        env=_env(),
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "commit"


def blame_line(repo: Path, commit: str, path: str, line: int) -> str:
    text = _run(
        ["blame", "--porcelain", "-L", f"{line},{line}", commit, "--", path],
        cwd=repo,
    )
    sha = text.split()[0]
    if not _HASH.fullmatch(sha):
        raise RuntimeError(f"git blame did not name a commit for {path}:{line} at {commit}")
    return sha


def _run(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_env(),
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git {' '.join(args)} failed\n{exc.stderr}") from exc
    return result.stdout


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key == "GIT_CONFIG_COUNT" or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            del env[key]
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env
