"""Build the sample service history as a git bundle.

Each fault is a branch whose parent is the healthy baseline. Author, committer,
dates, and messages are fixed so the commit hashes do not change between machines.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREES = HERE / "trees"

# (tree directory, branch, iso timestamp, subject, fault name or None)
COMMITS = (
    ("00-baseline", "main", "2026-01-06T15:00:00+00:00", "add checkout services", None),
    (
        "01-latency",
        "latency-spike",
        "2026-01-08T15:04:00+00:00",
        "rebuild the inventory index on each reserve",
        "latency_spike",
    ),
    (
        "02-error-rate",
        "error-rate-spike",
        "2026-01-09T16:12:00+00:00",
        "invert the payments retry check",
        "error_rate_spike",
    ),
    (
        "03-timeout",
        "dependency-timeout",
        "2026-01-12T11:30:00+00:00",
        "wait on a stuck payments connection",
        "dependency_timeout",
    ),
    (
        "04-bad-deploy",
        "bad-deploy",
        "2026-01-13T18:45:00+00:00",
        "scale charge amounts by 100",
        "bad_deploy",
    ),
)


def git_env(when: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key == "GIT_CONFIG_COUNT" or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
            del env[key]
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_AUTHOR_NAME"] = "Shop Dev"
    env["GIT_AUTHOR_EMAIL"] = "dev@shop.example"
    env["GIT_COMMITTER_NAME"] = "Shop Dev"
    env["GIT_COMMITTER_EMAIL"] = "dev@shop.example"
    if when is not None:
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    return env


def run_git(args: list[str], cwd: Path, env: dict[str, str], message: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            input=message,
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"git {' '.join(args)} failed\n{exc.stderr}") from exc
    return result.stdout.strip()


def copy_tree(tree: str, repo: Path) -> None:
    source = TREES / tree
    for path in source.iterdir():
        if path.is_file():
            shutil.copyfile(path, repo / path.name)


def build(repo: Path) -> list[dict]:
    env = git_env()
    run_git(["init", "-b", "main"], repo, env)
    rows = []
    baseline_hash = None
    for tree, branch, when, subject, fault in COMMITS:
        if branch != "main":
            run_git(["checkout", "-b", branch, "main"], repo, env)
        copy_tree(tree, repo)
        run_git(["add", "-A"], repo, git_env(when))
        run_git(
            ["commit", "--cleanup=verbatim", "--no-gpg-sign", "-F", "-"],
            repo,
            git_env(when),
            message=subject + "\n",
        )
        sha = run_git(["rev-parse", "HEAD"], repo, env)
        if fault is None:
            baseline_hash = sha
            parent = None
        else:
            parent = baseline_hash
            run_git(["checkout", "main"], repo, env)
        rows.append(
            {
                "branch": branch,
                "committed_at": when,
                "fault": fault,
                "hash": sha,
                "parent": parent,
                "subject": subject,
                "tree": tree,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the sample service git history.")
    parser.add_argument("--repo", type=Path, help="Directory to create. Defaults to a temporary directory.")
    parser.add_argument("--bundle", type=Path, default=HERE / "shop.bundle")
    parser.add_argument("--manifest", type=Path, default=HERE / "commits.json")
    args = parser.parse_args(argv)

    if args.repo is None:
        tmp = tempfile.TemporaryDirectory()
        repo = Path(tmp.name) / "repo"
    else:
        tmp = None
        repo = args.repo
    repo.mkdir(parents=True, exist_ok=False)

    try:
        rows = build(repo)
        if args.bundle.exists():
            args.bundle.unlink()
        run_git(["bundle", "create", str(args.bundle), "--all"], repo, git_env())
        args.manifest.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    main()
