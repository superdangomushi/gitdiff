"""Git command execution and repository queries."""


import subprocess
from typing import Optional


def run_git(*args: str) -> tuple[str, str, int]:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def check_git_repo() -> bool:
    _, _, rc = run_git("rev-parse", "--git-dir")
    return rc == 0


def get_current_branch() -> str:
    """Return the current branch name, or HEAD hash if detached."""
    stdout, _, rc = run_git("branch", "--show-current")
    name = stdout.strip()
    if rc == 0 and name:
        return name
    stdout, _, _ = run_git("rev-parse", "--short", "HEAD")
    return stdout.strip() or "unknown"


def check_ref(ref: str) -> bool:
    _, _, rc = run_git("rev-parse", "--verify", ref)
    return rc == 0


def get_diff_files(branch_a: str, branch_b: str) -> tuple[list[tuple[str, str]], Optional[str]]:
    ref = [f"{branch_a}...{branch_b}"] if branch_b else [branch_a]
    stdout, stderr, rc = run_git("diff", "--name-status", *ref)
    if rc != 0:
        return [], stderr.strip()
    files: list[tuple[str, str]] = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0][0]
        filename = parts[-1]
        files.append((status, filename))
    return files, None


def get_file_stats(branch_a: str, branch_b: str) -> dict[str, tuple[str, str]]:
    ref = [f"{branch_a}...{branch_b}"] if branch_b else [branch_a]
    stdout, _, _ = run_git("diff", "--numstat", *ref)
    stats: dict[str, tuple[str, str]] = {}
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed, filename = parts
            stats[filename] = (added, removed)
    return stats


def get_unstaged_files() -> set[str]:
    """Return paths with changes not yet staged (index vs working tree)."""
    stdout, _, rc = run_git("diff", "--name-only")
    if rc != 0:
        return set()
    return {line for line in stdout.splitlines() if line}


def get_file_diff(branch_a: str, branch_b: str, filename: str) -> str:
    ref = [f"{branch_a}...{branch_b}"] if branch_b else [branch_a]
    stdout, _, _ = run_git("diff", *ref, "--", filename)
    return stdout


def get_repo_root() -> Optional[str]:
    stdout, _, rc = run_git("rev-parse", "--show-toplevel")
    if rc == 0:
        return stdout.strip()
    return None
