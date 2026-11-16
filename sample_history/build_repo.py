"""Build the sample service history as a git bundle.

Main is a healthy line of unrelated edits. Each fault is a branch off the
main tip, plus one later commit that touches the same service and leaves
the fault line alone. Author, committer, dates, and messages are fixed so
the commit hashes do not change between machines. Fault subjects do not
name the fault.
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
    ("05-catalog", "main", "2026-01-07T10:15:00+00:00", "add sku-3 to the catalog", None),
    ("06-charge-limit", "main", "2026-01-07T14:40:00+00:00", "raise the charge ceiling", None),
    ("07-orders-note", "main", "2026-01-07T16:20:00+00:00", "note the payments deadline on orders", None),
    ("08-gateway-note", "main", "2026-01-07T18:05:00+00:00", "note the gateway handoff", None),
    ("09-receipt", "main", "2026-01-08T09:10:00+00:00", "add a receipt formatter", None),
    ("10-payments-timing", "main", "2026-01-08T11:25:00+00:00", "give payments a little more time", None),
    ("01-latency", "latency-spike", "2026-01-08T15:04:00+00:00", "update inventory reservation path", "latency_spike"),
    ("11-latency-extra", "latency-spike", "2026-01-08T17:45:00+00:00", "add sku-4 for the spring catalog", None),
    (
        "02-error-rate",
        "error-rate-spike",
        "2026-01-09T16:12:00+00:00",
        "adjust processor response handling",
        "error_rate_spike",
    ),
    (
        "12-error-extra",
        "error-rate-spike",
        "2026-01-09T18:30:00+00:00",
        "group processor codes for the dashboard",
        None,
    ),
    (
        "03-timeout",
        "dependency-timeout",
        "2026-01-12T11:30:00+00:00",
        "update the payments wait",
        "dependency_timeout",
    ),
    (
        "13-timeout-extra",
        "dependency-timeout",
        "2026-01-12T15:10:00+00:00",
        "treat code 14 as a decline",
        None,
    ),
    ("04-bad-deploy", "bad-deploy", "2026-01-13T18:45:00+00:00", "update charge amount handling", "bad_deploy"),
    (
        "14-bad-extra",
        "bad-deploy",
        "2026-01-14T10:20:00+00:00",
        "expose the charge ceiling to the receipt",
        None,
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
    seen = {"main"}
    current = "main"
    for tree, branch, when, subject, fault in COMMITS:
        if branch != current:
            if branch in seen:
                run_git(["checkout", branch], repo, env)
            else:
                run_git(["checkout", "-b", branch, "main"], repo, env)
                seen.add(branch)
            current = branch
        copy_tree(tree, repo)
        run_git(["add", "-A"], repo, git_env(when))
        run_git(
            ["commit", "--cleanup=verbatim", "--no-gpg-sign", "-F", "-"],
            repo,
            git_env(when),
            message=subject + "\n",
        )
        sha = run_git(["rev-parse", "HEAD"], repo, env)
        parent = run_git(["log", "-1", "--pretty=%P"], repo, env) or None
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
