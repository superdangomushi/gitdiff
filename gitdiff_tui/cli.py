"""Command-line argument parsing, validation, and application startup."""


import argparse
import subprocess
import sys

from .app import GitDiffApp
from .git import check_git_repo, check_ref, get_diff_files, get_file_stats


def _branch_completer(**kwargs):  # noqa: ANN003
    """Return git branch/tag names for argcomplete."""
    try:
        result = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=5,
        )
        branches = result.stdout.splitlines()
        result2 = subprocess.run(
            ["git", "tag", "--list"],
            capture_output=True, text=True, timeout=5,
        )
        branches += result2.stdout.splitlines()
        return branches
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="gitdiff",
        description="Interactively browse and edit diffs between two branches.",
        epilog=(
            "Keys:\n"
            "  j/k      move file list     Ctrl+D/U  scroll diff\n"
            "  e        enter edit mode    Ctrl+G    back to file list\n"
            "  Ctrl+S   save file          Ctrl+X    revert file\n"
            "  Ctrl+R   toggle deleted     Ctrl+P    toggle editor panel\n"
            "  Ctrl+F   toggle files + editor only view\n"
            "  b        change branches\n"
            "  q        quit"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    branch_a_arg = parser.add_argument("branch_a", metavar="branch-a", help="Base branch or ref")
    branch_b_arg = parser.add_argument("branch_b", metavar="branch-b", nargs="?", default="",
                                       help="Target branch or ref (omit to compare with working tree)")

    try:
        import argcomplete
        branch_a_arg.completer = _branch_completer  # type: ignore[attr-defined]
        branch_b_arg.completer = _branch_completer  # type: ignore[attr-defined]
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args = parser.parse_args()
    branch_a = args.branch_a
    branch_b = args.branch_b

    if not check_git_repo():
        print("Error: not inside a git repository.")
        sys.exit(1)

    refs_to_check = [branch_a] + ([branch_b] if branch_b else [])
    for ref in refs_to_check:
        if not check_ref(ref):
            print(f"Error: '{ref}' is not a valid branch or ref.")
            sys.exit(1)

    files, error = get_diff_files(branch_a, branch_b)
    if error:
        print(f"Error: {error}")
        sys.exit(1)

    if not files:
        print(f"No differences between '{branch_a}' and '{branch_b}'.")
        sys.exit(0)

    stats = get_file_stats(branch_a, branch_b)
    GitDiffApp(branch_a, branch_b, files, stats).run()
