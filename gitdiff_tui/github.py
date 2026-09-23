"""Fetch pull request review threads through the GitHub CLI."""


import json
import subprocess
from typing import Optional

from .git import run_git
from .models import ReviewComment, ReviewThread


_REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved isOutdated path line startLine diffSide
          comments(first: 100) {
            nodes { author { login } body createdAt diffHunk }
          }
        }
      }
    }
  }
}
"""


def _run_gh(*args: str) -> Optional[str]:
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _pr_head_branch(ref: str) -> str:
    """Strip a remote prefix such as ``origin/`` from ``ref``."""
    stdout, _, _ = run_git("remote")
    for remote in stdout.split():
        if ref.startswith(remote + "/"):
            return ref[len(remote) + 1:]
    return ref


def get_pr_review_threads(head: str) -> Optional[tuple[int, dict[str, list[ReviewThread]]]]:
    """Return (PR number, threads by path) for the PR opened from ``head``."""
    out = _run_gh("pr", "view", _pr_head_branch(head), "--json", "number")
    if out is None:
        return None
    number = json.loads(out)["number"]
    out = _run_gh(
        "api", "graphql",
        "-F", "owner={owner}", "-F", "name={repo}", "-F", f"number={number}",
        "-f", f"query={_REVIEW_THREADS_QUERY}",
    )
    if out is None:
        return None
    nodes = json.loads(out)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    threads: dict[str, list[ReviewThread]] = {}
    for node in nodes:
        comments = [
            ReviewComment(
                author=(c.get("author") or {}).get("login", "ghost"),
                body=c.get("body", ""),
                created_at=c.get("createdAt", ""),
            )
            for c in node["comments"]["nodes"]
        ]
        first = node["comments"]["nodes"][0] if node["comments"]["nodes"] else {}
        threads.setdefault(node["path"], []).append(ReviewThread(
            path=node["path"],
            side=node.get("diffSide") or "RIGHT",
            line=node.get("line"),
            start_line=node.get("startLine"),
            resolved=node.get("isResolved", False),
            outdated=node.get("isOutdated", False),
            diff_hunk=first.get("diffHunk", ""),
            comments=comments,
        ))
    return number, threads
