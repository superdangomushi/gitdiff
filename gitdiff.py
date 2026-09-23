#!/usr/bin/env python3
"""gitdiff - Interactive git branch diff viewer"""

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.geometry import Offset
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import (
    Header, Footer, Label, Static, Input, Button, TextArea, Tree
)
from textual.widgets.tree import TreeNode
from textual.containers import Horizontal, Vertical, ScrollableContainer
from rich.console import Group
from rich.markdown import Markdown
from rich.rule import Rule
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.syntax import Syntax
from rich.text import Text as RichText


STATUS_STYLES: dict[str, tuple[str, str, str]] = {
    "A": ("green",   "[+]", "Added"),
    "M": ("yellow",  "[~]", "Modified"),
    "D": ("red",     "[-]", "Deleted"),
    "R": ("cyan",    "[→]", "Renamed"),
    "C": ("blue",    "[©]", "Copied"),
    "T": ("magenta", "[T]", "Type changed"),
}

EXT_LANG: dict[str, str] = {
    ".py": "python",   ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx",     ".jsx": "javascript",
    ".sh": "bash",     ".bash": "bash",
    ".md": "markdown", ".json": "json",
    ".yaml": "yaml",   ".yml": "yaml",
    ".css": "css",     ".html": "html",     ".xml": "xml",
    ".go": "go",       ".rs": "rust",       ".c": "c",
    ".cpp": "cpp",     ".h": "c",           ".rb": "ruby",
    ".php": "php",     ".java": "java",     ".kt": "kotlin",
    ".sql": "sql",     ".toml": "toml",
}


def get_language(filename: str) -> Optional[str]:
    return EXT_LANG.get(Path(filename).suffix.lower())


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# GitHub PR review comments (via gh)
# ---------------------------------------------------------------------------

@dataclass
class ReviewComment:
    author: str
    body: str
    created_at: str


@dataclass
class ReviewThread:
    path: str
    side: str             # 'RIGHT' (new file) | 'LEFT' (old file)
    line: Optional[int]   # None when the thread is outdated
    start_line: Optional[int]
    resolved: bool
    outdated: bool
    diff_hunk: str
    comments: list[ReviewComment] = field(default_factory=list)

    @property
    def lines(self) -> range:
        if self.line is None:
            return range(0)
        return range(self.start_line or self.line, self.line + 1)


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


def render_review_threads(threads: list["ReviewThread"]) -> Group:
    parts = []
    for thread in threads:
        where = f"{thread.path}:{thread.line}"
        tags = ""
        if thread.resolved:
            tags += "  [green](resolved)[/green]"
        if thread.outdated:
            tags += "  [dim](outdated)[/dim]"
        parts.append(RichText.from_markup(f"[bold yellow]{where}[/bold yellow]{tags}"))
        hunk = "\n".join(thread.diff_hunk.splitlines()[-4:])
        if hunk:
            parts.append(Syntax(hunk, "diff", theme="monokai", word_wrap=True))
        for comment in thread.comments:
            date = comment.created_at.replace("T", " ").rstrip("Z")
            parts.append(RichText.from_markup(
                f"\n[bold cyan]@{comment.author}[/bold cyan]  [dim]{date}[/dim]"
            ))
            parts.append(Markdown(comment.body))
        parts.append(Rule(style="dim"))
    return Group(*parts)


# ---------------------------------------------------------------------------
# Diff parsing & rendering
# ---------------------------------------------------------------------------

def _hunk_offset(header: str, default: int, sign: str = "+") -> int:
    """Return the number of new-file (``sign='+'``) or old-file (``'-'``)
    lines that precede a hunk.

    ``@@ -a,b +c,d @@`` starts at line ``c``, except that an empty new range
    (``d == 0``) names the line the hunk comes *after*.
    """
    m = re.search(re.escape(sign) + r"(\d+)(?:,(\d+))?", header)
    if not m:
        return default
    start = int(m.group(1))
    return start if m.group(2) == "0" else start - 1


def _hunk_new_offset(header: str, default: int) -> int:
    return _hunk_offset(header, default, "+")


def walk_diff(diff_text: str) -> Iterator[tuple[str, str, Optional[int], Optional[int]]]:
    """Yield (kind, content, old_lineno, new_lineno) for every hunk line.

    kind: 'add' | 'del' | 'ctx'. Line numbers are 1-based; the side a line
    does not exist on is None.
    """
    old_lineno = new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ")):
            in_hunk = False
            continue
        if line.startswith("@@"):
            old_lineno = _hunk_offset(line, old_lineno, "-")
            new_lineno = _hunk_offset(line, new_lineno, "+")
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("+"):
            new_lineno += 1
            yield "add", line[1:], None, new_lineno
        elif line.startswith("-"):
            old_lineno += 1
            yield "del", line[1:], old_lineno, None
        else:  # context line (starts with space)
            old_lineno += 1
            new_lineno += 1
            yield "ctx", line[1:], old_lineno, new_lineno


def parse_diff_lines(diff_text: str) -> list[tuple[str, str, Optional[int]]]:
    """Parse diff text into (kind, content, new_lineno) tuples.

    kind     : 'add' | 'del' | 'ctx'
    new_lineno: 1-based line number in the new file; None for deleted lines.
    """
    return [(kind, content, new) for kind, content, _old, new in walk_diff(diff_text)]


def map_threads_to_diff(
    diff_text: str, threads: list["ReviewThread"]
) -> dict[int, list["ReviewThread"]]:
    """Map indices into ``parse_diff_lines(diff_text)`` to the threads on them."""
    right: dict[int, list[ReviewThread]] = {}
    left: dict[int, list[ReviewThread]] = {}
    for thread in threads:
        target = left if thread.side == "LEFT" else right
        for ln in thread.lines:
            target.setdefault(ln, []).append(thread)
    result: dict[int, list[ReviewThread]] = {}
    for i, (kind, _content, old, new) in enumerate(walk_diff(diff_text)):
        found = left.get(old, []) if kind == "del" else right.get(new, [])
        if found:
            result[i] = found
    return result


def map_threads_to_buffer(
    diff_text: str, deleted: set[int], line_count: int, threads: list["ReviewThread"]
) -> dict[int, list["ReviewThread"]]:
    """Map edit-buffer line indices (see ``build_edit_buffer``) to threads."""
    old_of_deleted = [old for kind, _c, old, _n in walk_diff(diff_text) if kind == "del"]
    deleted_rows = sorted(deleted)
    file_rows = [i for i in range(line_count) if i not in deleted]
    result: dict[int, list[ReviewThread]] = {}
    for thread in threads:
        for ln in thread.lines:
            row: Optional[int] = None
            if thread.side == "LEFT":
                if ln in old_of_deleted:
                    k = old_of_deleted.index(ln)
                    if k < len(deleted_rows):
                        row = deleted_rows[k]
            elif 0 < ln <= len(file_rows):
                row = file_rows[ln - 1]
            if row is not None:
                result.setdefault(row, []).append(thread)
    return result


def parse_deleted_lines(diff_text: str) -> list[tuple[int, str]]:
    """Return (anchor, content) for every deleted line in the diff.

    anchor: how many new-file lines precede the deleted line, i.e. the 0-based
    index in the new file it would be restored in front of.
    """
    result: list[tuple[int, str]] = []
    new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ")):
            in_hunk = False
            continue
        if line.startswith("@@"):
            new_lineno = _hunk_new_offset(line, new_lineno)
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("-"):
            result.append((new_lineno, line[1:]))
        else:
            new_lineno += 1

    return result


def build_edit_buffer(
    content: str,
    diff_text: str,
) -> tuple[str, set[int], set[int]]:
    """Interleave the diff's deleted lines into ``content`` for editing.

    Returns (buffer, added, deleted): 0-based buffer line indices of the
    added lines (green) and of the inserted deleted lines (red).
    """
    file_lines = content.split("\n")
    added_new = {
        lineno - 1
        for kind, _content, lineno in parse_diff_lines(diff_text)
        if kind == "add" and lineno is not None
    }
    deletions = parse_deleted_lines(diff_text)

    lines: list[str] = []
    added: set[int] = set()
    deleted: set[int] = set()
    d = 0
    for i, line in enumerate(file_lines):
        while d < len(deletions) and deletions[d][0] <= i:
            deleted.add(len(lines))
            lines.append(deletions[d][1])
            d += 1
        if i in added_new:
            added.add(len(lines))
        lines.append(line)
    # Deletions past the end of the file (e.g. content no longer on disk)
    # go before the empty string that a trailing newline splits into.
    tail = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
    for _anchor, text in deletions[d:]:
        deleted.add(tail)
        lines.insert(tail, text)
        tail += 1

    return "\n".join(lines), added, deleted


def build_editor_view(
    diff_lines: list[tuple[str, str, Optional[int]]],
    show_deleted: bool,
    commented: frozenset[int] | set[int] = frozenset(),
) -> RichText:
    """Build Rich Text with green/red diff highlights and line numbers.

    Lines whose index is in ``commented`` (PR review comments) are yellow.
    """
    text = RichText()
    line_nums = [ln for _, _, ln in diff_lines if ln is not None]
    width = len(str(max(line_nums))) if line_nums else 1

    for i, (kind, content, lineno) in enumerate(diff_lines):
        if kind == "del" and not show_deleted:
            continue
        gutter = f"{lineno:>{width}} " if lineno is not None else f"{'~':>{width}} "
        if i in commented:
            text.append(gutter + content + "\n", style=_COMMENT_STYLE)
        elif kind == "add":
            text.append(gutter + content + "\n", style="on dark_green")
        elif kind == "del":
            text.append(gutter + content + "\n", style="on dark_red")
        else:
            text.append(gutter + content + "\n")

    return text


# ---------------------------------------------------------------------------
# TUI widgets
# ---------------------------------------------------------------------------

_ADD_BG = RichStyle(bgcolor="dark_green")
_DEL_BG = RichStyle(bgcolor="dark_red")
_COMMENT_STYLE = "black on yellow"
_COMMENT_BG = RichStyle(color="black", bgcolor="yellow")

_REMAP_DEBOUNCE = 0.1  # seconds to wait after a keystroke before re-anchoring


def remap_line_indices(
    old_lines: list[str],
    new_lines: list[str],
    indices: set[int],
) -> set[int]:
    """Carry 0-based line indices from ``old_lines`` over to ``new_lines``.

    Lines that survived the edit keep their marker at the shifted position;
    lines that were removed lose it.
    """
    if not indices:
        return set()
    if old_lines == new_lines:
        return set(indices)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    moved: set[int] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in ("equal", "replace"):
            continue  # 'insert' has no old lines, 'delete' has no new ones
        for i in indices:
            if not i1 <= i < i2:
                continue
            j = j1 + (i - i1)
            if j < j2:  # a shrinking 'replace' can drop the tail
                moved.add(j)
    return moved


class DiffTextArea(TextArea):
    """TextArea that highlights added/deleted lines with green/red backgrounds.

    Deleted lines are shown inline but are not part of the file: they are
    read-only, dropped on save, and Backspace on one restores it.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._added_lines: set[int] = set()   # 0-based line indices → green
        self._deleted_lines: set[int] = set() # 0-based line indices → red
        self._anchor_lines: list[str] = []    # buffer contents the indices refer to
        self._comment_rows: dict[int, list[ReviewThread]] = {}  # → yellow, clickable
        self._remap_timer = None

    def set_diff_lines(self, added: set[int], deleted: set[int]) -> None:
        if self._remap_timer is not None:
            self._remap_timer.stop()
            self._remap_timer = None
        self._added_lines = set(added)
        self._deleted_lines = set(deleted)
        self._anchor_lines = self.text.split("\n")
        self.refresh()

    def set_comment_rows(self, rows: dict[int, list["ReviewThread"]]) -> None:
        """Set comment rows; call right after ``set_diff_lines`` (same anchor)."""
        self._comment_rows = dict(rows)
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        """Clicking a commented (yellow) line shows its review threads."""
        if not self._comment_rows:
            return
        offset = event.get_content_offset(self)
        if offset is None:
            return
        self._sync_diff_lines()
        row = self._document_row(offset.y)
        if row in self._comment_rows:
            self.app.show_review_threads(self._comment_rows[row])

    def on_key(self, event) -> None:
        """Capture Tab for indentation and Escape to exit edit mode."""
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            if not self._touches_deleted(*self.selection):
                self.insert("\t")
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.action_exit_edit()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Re-anchor the highlights after the buffer is edited."""
        if not self._added_lines and not self._deleted_lines and not self._comment_rows:
            return
        if self._remap_timer is not None:
            self._remap_timer.stop()
        self._remap_timer = self.set_timer(_REMAP_DEBOUNCE, self._remap_diff_lines)

    def _sync_diff_lines(self) -> None:
        """Re-anchor the highlights now instead of waiting for the debounce."""
        if self._remap_timer is not None:
            self._remap_timer.stop()
        self._remap_diff_lines()

    def saved_text(self) -> str:
        """Buffer contents without the (unrestored) deleted lines."""
        self._sync_diff_lines()
        return "\n".join(
            line for i, line in enumerate(self.text.split("\n"))
            if i not in self._deleted_lines
        )

    def _touches_deleted(self, start, end) -> bool:
        if not self._deleted_lines:
            return False
        self._sync_diff_lines()
        top, bottom = sorted((start[0], end[0]))
        return any(top <= row <= bottom for row in self._deleted_lines)

    def action_delete_left(self) -> None:
        """Backspace on a deleted (red) line restores it instead of editing."""
        if self.selection.is_empty and self._deleted_lines:
            self._sync_diff_lines()
            row = self.cursor_location[0]
            if row in self._deleted_lines:
                self._deleted_lines.discard(row)
                self.refresh()
                return
        super().action_delete_left()

    def _delete_via_keyboard(self, start, end):
        if self._touches_deleted(start, end):
            self.notify("Deleted line: press Backspace to restore it first.",
                        severity="warning")
            return None
        return super()._delete_via_keyboard(start, end)

    def _replace_via_keyboard(self, insert, start, end):
        if self._touches_deleted(start, end):
            self.notify("Deleted line: press Backspace to restore it first.",
                        severity="warning")
            return None
        return super()._replace_via_keyboard(insert, start, end)

    def _remap_diff_lines(self) -> None:
        self._remap_timer = None
        new_lines = self.text.split("\n")
        if new_lines == self._anchor_lines:
            return
        self._added_lines = remap_line_indices(
            self._anchor_lines, new_lines, self._added_lines
        )
        self._deleted_lines = remap_line_indices(
            self._anchor_lines, new_lines, self._deleted_lines
        )
        comment_rows: dict[int, list[ReviewThread]] = {}
        for row, threads in self._comment_rows.items():
            for new_row in remap_line_indices(self._anchor_lines, new_lines, {row}):
                comment_rows[new_row] = threads
        self._comment_rows = comment_rows
        self._anchor_lines = new_lines
        self.refresh()

    def _document_row(self, y: int) -> Optional[int]:
        """Map a screen row to the document line it renders.

        A soft-wrapped line occupies several screen rows, so the row index is
        not the line index; ``scroll_offset`` is also the integer offset the
        base widget actually renders with, unlike the animated ``scroll_y``.
        """
        y_offset = y + self.scroll_offset.y
        if y_offset < 0:
            return None
        wrapped = getattr(self, "wrapped_document", None)
        if wrapped is None:  # Textual too old to soft wrap: rows are lines
            return y_offset if y_offset < self.document.line_count else None
        if y_offset >= wrapped.height:
            return None  # padding below the last line
        return wrapped.offset_to_location(Offset(0, y_offset))[0]

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        doc_y = self._document_row(y)
        if doc_y is None:
            return strip
        if doc_y in self._comment_rows:
            bg = _COMMENT_BG
        elif doc_y in self._added_lines:
            bg = _ADD_BG
        elif doc_y in self._deleted_lines:
            bg = _DEL_BG
        else:
            return strip
        new_segs = [
            Segment(s.text, (s.style or RichStyle()) + bg, s.control)
            for s in strip
        ]
        return Strip(new_segs, strip.cell_length)


class EditorView(Static):
    """Read-only diff view; clicking a yellow (commented) line opens its threads."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.row_threads: dict[int, list[ReviewThread]] = {}

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is not None and offset.y in self.row_threads:
            self.app.show_review_threads(self.row_threads[offset.y])


def _file_leaf_label(
    status: str, name: str, stats: tuple[str, str], unstaged: bool = False,
    comments: int = 0,
) -> str:
    color, badge, _ = STATUS_STYLES.get(status, ("white", "[?]", "Unknown"))
    added, removed = stats
    stats_str = f"  [green]+{added}[/green] [red]-{removed}[/red]" if added != "-" else ""
    name_str = f"[yellow]{name}[/yellow]" if unstaged else name
    comment_str = f"  [black on yellow] {comments} [/black on yellow]" if comments else ""
    return f"[{color}]{badge}[/{color}] {name_str}{stats_str}{comment_str}"


class PanelSplitter(Static):
    """Draggable vertical bar that resizes the diff and editor panels."""

    MIN_WIDTH = 10

    def __init__(self, left_id: str, right_id: str, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._left_id = left_id
        self._right_id = right_id
        self._dragging = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        left = self.app.query_one(f"#{self._left_id}")
        right = self.app.query_one(f"#{self._right_id}")
        start = left.region.x
        total = right.region.right - start - self.region.width
        if total <= self.MIN_WIDTH * 2:
            return
        width = max(self.MIN_WIDTH, min(event.screen_x - start, total - self.MIN_WIDTH))
        left.styles.width = f"{width}fr"
        right.styles.width = f"{total - width}fr"
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("-dragging")
            self.release_mouse()
            event.stop()


class ChangeBranchScreen(ModalScreen):
    """Modal screen for changing comparison branches."""

    CSS = """
    ChangeBranchScreen {
        align: center middle;
    }

    #dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }

    #dialog-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    .branch-label {
        padding-top: 1;
    }

    #button-row {
        align-horizontal: right;
        padding-top: 1;
        height: 3;
    }

    Button {
        margin-left: 1;
    }
    """

    def __init__(self, branch_a: str, branch_b: str) -> None:
        super().__init__()
        self.current_a = branch_a
        self.current_b = branch_b

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Change Comparison Branches", id="dialog-title")
            yield Label("Branch A:", classes="branch-label")
            yield Input(value=self.current_a, id="input-a", placeholder="branch-a")
            yield Label("Branch B:", classes="branch-label")
            yield Input(value=self.current_b, id="input-b", placeholder="branch-b")
            with Horizontal(id="button-row"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Apply", variant="primary", id="btn-apply")

    def on_mount(self) -> None:
        self.query_one("#input-a", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-apply":
            self._apply()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._apply()

    def _apply(self) -> None:
        a = self.query_one("#input-a", Input).value.strip()
        b = self.query_one("#input-b", Input).value.strip()
        if a and b:
            self.dismiss((a, b))


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class GitDiffApp(App):
    CSS = """
    Screen {
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        min-width: 20;
        border-right: solid $primary-darken-2;
        background: $surface;
    }

    #sidebar-title {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
        text-align: center;
    }

    #file-list {
        height: 1fr;
        padding: 0 1;
    }

    #diff-panel {
        width: 1fr;
    }

    #panel-splitter {
        width: 1;
        height: 1fr;
        background: $primary-darken-2;
    }

    #panel-splitter:hover, #panel-splitter.-dragging {
        background: $accent;
    }

    #diff-title {
        background: $secondary;
        color: $text;
        padding: 0 1;
        height: 1;
    }

    #diff-scroll {
        height: 1fr;
        overflow-y: auto;
        overflow-x: auto;
    }

    #diff-content {
        padding: 0 1;
        width: auto;
    }

    #comment-scroll {
        height: 1fr;
        overflow-y: auto;
        display: none;
    }

    #comment-content {
        padding: 0 1;
    }

    #editor-panel {
        width: 1fr;
    }

    #editor-title {
        background: $accent;
        color: $text;
        padding: 0 1;
        height: 1;
    }

    #editor-view-scroll {
        height: 1fr;
        overflow-y: auto;
        overflow-x: auto;
    }

    #editor-view {
        padding: 0 1;
        width: auto;
    }

    #editor {
        height: 1fr;
        display: none;
    }
    """

    BINDINGS = [
        ("q",      "quit",           "Quit"),
        ("j",      "move_down",      "Down"),
        ("k",      "move_up",        "Up"),
        ("down",   "move_down",      ""),
        ("up",     "move_up",        ""),
        ("ctrl+d", "page_down",      "Page ↓"),
        ("ctrl+u", "page_up",        "Page ↑"),
        ("e",      "enter_edit",     "Edit"),
        ("b",      "change_branch",  "Branch"),
        Binding("ctrl+r", "toggle_deleted",  "Del Lines",    priority=True),
        Binding("ctrl+p", "toggle_editor",   "Editor Panel", priority=True),
        Binding("ctrl+f", "toggle_files_editor", "Files+Editor", priority=True),
        Binding("ctrl+s", "write_out",       "Write Out",    priority=True),
        Binding("ctrl+x", "revert_file",     "Revert",       priority=True),
        Binding("escape", "exit_edit",        "Back",         priority=True),
        Binding("ctrl+g", "focus_list",      "File List",    priority=True),
    ]

    def __init__(self, branch_a: str, branch_b: str, files: list, stats: dict) -> None:
        super().__init__()
        self.branch_a = branch_a
        self.branch_b = branch_b
        self.files = files
        self.file_stats = stats
        self._current_index: int = 0
        self._repo_root: Optional[str] = get_repo_root()
        self._show_deleted: bool = True
        self._show_editor: bool = True
        self._files_editor_only: bool = False
        self._diff_lines: list[tuple[str, str, Optional[int]]] = []
        self._unstaged: set[str] = set()
        self._leaf_nodes: dict[int, TreeNode] = {}
        self._pr_number: Optional[int] = None
        self._pr_threads: dict[str, list[ReviewThread]] = {}
        # Index into self._diff_lines → review threads on that line
        self._diff_threads: dict[int, list[ReviewThread]] = {}

    @property
    def _b_label(self) -> str:
        return self.branch_b if self.branch_b else "Working Tree"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static(self._sidebar_title(), id="sidebar-title")
                tree: Tree[int] = Tree("Files", id="file-list")
                tree.show_root = False
                tree.guide_depth = 2
                yield tree
            with Vertical(id="diff-panel"):
                yield Static(f" {self.branch_a}  →  {self._b_label}", id="diff-title")
                with ScrollableContainer(id="diff-scroll"):
                    yield Static("← Select a file", id="diff-content")
                with ScrollableContainer(id="comment-scroll"):
                    yield Static("", id="comment-content")
            yield PanelSplitter("diff-panel", "editor-panel", id="panel-splitter")
            with Vertical(id="editor-panel"):
                yield Static(" Editor", id="editor-title")
                with ScrollableContainer(id="editor-view-scroll"):
                    yield EditorView("← Select a file", id="editor-view")
                yield DiffTextArea("", id="editor", show_line_numbers=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"gitdiff  {self.branch_a} → {self._b_label}  (on {get_current_branch()})"
        tree = self.query_one("#file-list", Tree)
        self._build_file_tree(tree)
        tree.focus()
        first_leaf = self._first_leaf(tree.root)
        if first_leaf is not None:
            tree.move_cursor(first_leaf)
            self._current_index = first_leaf.data
            self._load_file(first_leaf.data)
        self._fetch_review_threads()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        data = event.node.data
        if isinstance(data, int):
            self._current_index = data
            self._load_file(data)

    def action_move_down(self) -> None:
        self.query_one("#file-list", Tree).action_cursor_down()

    def action_move_up(self) -> None:
        self.query_one("#file-list", Tree).action_cursor_up()

    def _page_scroll_target(self) -> ScrollableContainer:
        # With the diff panel hidden, page keys scroll the editor view instead
        target = "#editor-view-scroll" if self._files_editor_only else "#diff-scroll"
        return self.query_one(target, ScrollableContainer)

    def action_page_down(self) -> None:
        self._page_scroll_target().scroll_page_down()

    def action_page_up(self) -> None:
        self._page_scroll_target().scroll_page_up()

    def action_exit_edit(self) -> None:
        if self.query_one("#comment-scroll").display:
            self._close_review_threads()
        elif self.query_one("#editor").display:
            self._exit_edit_mode()

    def action_focus_list(self) -> None:
        self._exit_edit_mode()
        self.query_one("#file-list", Tree).focus()

    def action_enter_edit(self) -> None:
        if not self.files:
            return
        status, _ = self.files[self._current_index]
        if status == "D":
            self.notify("Cannot edit a deleted file.", severity="warning")
            return
        self._enter_edit_mode()

    def action_toggle_editor(self) -> None:
        self._show_editor = not self._show_editor
        if self._files_editor_only:
            self.notify(f"Editor panel: {'on' if self._show_editor else 'off'} (after ^F)")
            return
        panel = self.query_one("#editor-panel")
        panel.display = self._show_editor
        self._update_splitter()
        if not self._show_editor:
            # If hiding while in edit mode, exit edit mode first
            if self.query_one("#editor").display:
                self._exit_edit_mode()
            self.query_one("#file-list", Tree).focus()

    def action_toggle_files_editor(self) -> None:
        """Show only the file list and editor panel, hiding the diff panel."""
        self._files_editor_only = not self._files_editor_only
        self.query_one("#diff-panel").display = not self._files_editor_only
        # The editor panel is always visible in this mode; restore ^P state on exit
        panel = self.query_one("#editor-panel")
        panel.display = self._files_editor_only or self._show_editor
        self._update_splitter()
        if not panel.display:
            if self.query_one("#editor").display:
                self._exit_edit_mode()
            self.query_one("#file-list", Tree).focus()

    def action_toggle_deleted(self) -> None:
        self._show_deleted = not self._show_deleted
        label = "shown" if self._show_deleted else "hidden"
        self.notify(f"Deleted lines: {label}")
        self._refresh_editor_view()
        self._update_editor_title()

    def action_write_out(self) -> None:
        if not self.files or self._repo_root is None:
            return
        status, filename = self.files[self._current_index]
        if status == "D":
            self.notify("Cannot save a deleted file.", severity="warning")
            return
        filepath = os.path.join(self._repo_root, filename)
        editor = self.query_one("#editor", DiffTextArea)
        try:
            content = editor.saved_text()
            Path(filepath).write_text(content, encoding="utf-8")
            self.notify(f"Saved: {filename}")
            # Refresh diff, view, and editor highlights after save
            diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
            self._set_diff(filename, diff_text)
            self._render_diff(self._current_index)
            self._refresh_editor_view()
            self._load_editor_buffer(content, diff_text, keep_cursor=True)
            self._refresh_unstaged()
            self._update_leaf_label(self._current_index)
        except OSError as e:
            self.notify(f"Error saving: {e}", severity="error")

    def action_revert_file(self) -> None:
        if not self.files or self._repo_root is None:
            return
        status, filename = self.files[self._current_index]
        if status == "D":
            return
        filepath = os.path.join(self._repo_root, filename)
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except OSError:
            content = ""
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        self._load_editor_buffer(content, diff_text)
        self.notify(f"Reverted: {filename}")

    def action_change_branch(self) -> None:
        def on_dismiss(result) -> None:
            if result is None:
                return
            new_a, new_b = result
            if not check_ref(new_a):
                self.notify(f"'{new_a}' is not a valid branch or ref.", severity="error")
                return
            if new_b and not check_ref(new_b):
                self.notify(f"'{new_b}' is not a valid branch or ref.", severity="error")
                return
            files, error = get_diff_files(new_a, new_b)
            if error:
                self.notify(f"Error: {error}", severity="error")
                return
            stats = get_file_stats(new_a, new_b)
            self.branch_a = new_a
            self.branch_b = new_b
            self.files = files
            self.file_stats = stats
            self._current_index = 0
            self._pr_threads = {}
            self._reload_file_list()
            self._fetch_review_threads()

        self.push_screen(ChangeBranchScreen(self.branch_a, self.branch_b), on_dismiss)

    # ---- PR review comments ----

    @work(thread=True, exclusive=True, group="pr-comments")
    def _fetch_review_threads(self) -> None:
        head = self.branch_b or get_current_branch()
        result = get_pr_review_threads(head)
        if result is not None:
            self.call_from_thread(self._apply_review_threads, head, *result)

    def _apply_review_threads(
        self, head: str, number: int, threads: dict[str, list[ReviewThread]]
    ) -> None:
        if head != (self.branch_b or get_current_branch()):
            return  # branches changed while fetching
        self._pr_number = number
        self._pr_threads = threads
        for index in self._leaf_nodes:
            self._update_leaf_label(index)
        total = sum(len(t) for t in threads.values())
        self.notify(f"PR #{number}: {total} review thread(s)")
        if not self.files:
            return
        _, filename = self.files[self._current_index]
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        if self._diff_lines:
            self._set_diff(filename, diff_text)
            self._refresh_editor_view()
        editor = self.query_one("#editor", DiffTextArea)
        if editor.display:
            editor.set_comment_rows(map_threads_to_buffer(
                diff_text, editor._deleted_lines, editor.document.line_count,
                self._pr_threads.get(filename, []),
            ))

    def show_review_threads(self, threads: list[ReviewThread]) -> None:
        """Show ``threads`` in place of the diff summary (Esc to go back)."""
        self.query_one("#comment-content", Static).update(render_review_threads(threads))
        self.query_one("#diff-scroll").display = False
        scroll = self.query_one("#comment-scroll", ScrollableContainer)
        scroll.display = True
        scroll.scroll_home(animate=False)
        count = sum(len(t.comments) for t in threads)
        pr = f"PR #{self._pr_number}  " if self._pr_number else ""
        self.query_one("#diff-title", Static).update(
            f" {pr}[yellow]{count} comment(s)[/yellow]  [dim]Esc Back[/dim]"
        )
        # Ctrl+F hides the diff panel; bring it back while the comments are open.
        self.query_one("#diff-panel").display = True
        self._update_splitter()

    def _close_review_threads(self) -> None:
        if not self.query_one("#comment-scroll").display:
            return
        self.query_one("#comment-scroll").display = False
        self.query_one("#diff-scroll").display = True
        self.query_one("#diff-panel").display = not self._files_editor_only
        self._update_splitter()
        if self.files:
            self._render_diff(self._current_index)

    # ---- internal helpers ----

    def _update_splitter(self) -> None:
        # The splitter only makes sense while both the diff and editor panels are shown.
        self.query_one("#panel-splitter").display = (
            self.query_one("#diff-panel").display and self.query_one("#editor-panel").display
        )

    def _refresh_unstaged(self) -> None:
        # Only meaningful when comparing against the working tree.
        self._unstaged = get_unstaged_files() if not self.branch_b else set()

    def _sidebar_title(self) -> str:
        title = f" Files ({len(self.files)})"
        if not self.branch_b:
            title += "  [dim][yellow]unstaged[/yellow][/dim]"
        return title

    def _update_leaf_label(self, index: int) -> None:
        node = self._leaf_nodes.get(index)
        if node is None:
            return
        status, filename = self.files[index]
        stats = self.file_stats.get(filename, ("-", "-"))
        node.set_label(_file_leaf_label(
            status, filename.split("/")[-1], stats, filename in self._unstaged,
            len(self._pr_threads.get(filename, [])),
        ))

    def _build_file_tree(self, tree: Tree) -> None:
        """Populate the Tree widget with files grouped by folder."""
        tree.clear()
        tree.root.expand()
        self._refresh_unstaged()
        self._leaf_nodes = {}
        dir_nodes: dict[tuple[str, ...], TreeNode] = {(): tree.root}

        # Sort by path so siblings group together; keep original index for diff lookup.
        indexed = sorted(enumerate(self.files), key=lambda x: x[1][1].split("/"))

        for orig_idx, (status, filename) in indexed:
            parts = filename.split("/")
            for depth in range(1, len(parts)):
                key = tuple(parts[:depth])
                if key not in dir_nodes:
                    parent = dir_nodes[key[:-1]]
                    dir_nodes[key] = parent.add(
                        f"[bold]{parts[depth - 1]}/[/bold]", expand=True
                    )
            parent = dir_nodes[tuple(parts[:-1])]
            stats = self.file_stats.get(filename, ("-", "-"))
            label = _file_leaf_label(
                status, parts[-1], stats, filename in self._unstaged,
                len(self._pr_threads.get(filename, [])),
            )
            self._leaf_nodes[orig_idx] = parent.add_leaf(label, data=orig_idx)

    def _first_leaf(self, node: TreeNode) -> Optional[TreeNode]:
        if node.allow_expand is False or not node.children:
            return node if isinstance(node.data, int) else None
        for child in node.children:
            found = self._first_leaf(child)
            if found is not None:
                return found
        return None

    def _enter_edit_mode(self) -> None:
        if not self.files or self._repo_root is None:
            return
        _, filename = self.files[self._current_index]
        filepath = os.path.join(self._repo_root, filename)
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except OSError:
            content = ""
        editor = self.query_one("#editor", DiffTextArea)
        editor.language = get_language(filename)
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        self._load_editor_buffer(content, diff_text)
        self.query_one("#editor-view-scroll").display = False
        editor.display = True
        editor.focus()
        self._update_editor_title(edit_mode=True)

    def _load_editor_buffer(
        self, content: str, diff_text: str, keep_cursor: bool = False
    ) -> None:
        """Load ``content`` plus the diff's deleted lines into the editor."""
        editor = self.query_one("#editor", DiffTextArea)
        buffer, added, deleted = build_edit_buffer(content, diff_text)
        if buffer != editor.text:
            cursor = editor.cursor_location
            scroll = editor.scroll_offset
            editor.load_text(buffer)
            if keep_cursor:
                editor.move_cursor(cursor)
                editor.scroll_to(scroll.x, scroll.y, animate=False)
        editor.set_diff_lines(added, deleted)
        _, filename = self.files[self._current_index]
        editor.set_comment_rows(map_threads_to_buffer(
            diff_text, deleted, editor.document.line_count,
            self._pr_threads.get(filename, []),
        ))

    def _exit_edit_mode(self) -> None:
        self.query_one("#editor").display = False
        self.query_one("#editor-view-scroll").display = True
        self._update_editor_title(edit_mode=False)

    def _set_diff(self, filename: str, diff_text: str) -> None:
        self._diff_lines = parse_diff_lines(diff_text)
        self._diff_threads = map_threads_to_diff(diff_text, self._pr_threads.get(filename, []))

    def _load_file(self, index: int) -> None:
        self._close_review_threads()
        self._render_diff(index)
        status, filename = self.files[index]
        self._diff_threads = {}
        self.query_one("#editor-view", EditorView).row_threads = {}
        if status == "D" or self._repo_root is None:
            self._diff_lines = []
            self.query_one("#editor-view", Static).update("[dim](deleted file)[/dim]")
            self.query_one("#editor-title", Static).update(" Editor  [dim](deleted)[/dim]")
            return
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        if not diff_text:
            self._diff_lines = []
            self.query_one("#editor-view", Static).update("[dim](no diff available)[/dim]")
            self.query_one("#editor-title", Static).update(f" Editor  [dim]{filename}[/dim]")
            return
        self._set_diff(filename, diff_text)
        self._refresh_editor_view()
        self._update_editor_title()

    def _refresh_editor_view(self) -> None:
        view = self.query_one("#editor-view", EditorView)
        if self._diff_lines:
            view.update(build_editor_view(
                self._diff_lines, self._show_deleted, set(self._diff_threads)
            ))
            visible = [
                i for i, (kind, _c, _n) in enumerate(self._diff_lines)
                if kind != "del" or self._show_deleted
            ]
            view.row_threads = {
                row: self._diff_threads[i]
                for row, i in enumerate(visible) if i in self._diff_threads
            }
        else:
            view.update("[dim]No diff data available.[/dim]")

    def _update_editor_title(self, edit_mode: bool = False) -> None:
        if not self.files:
            return
        _, filename = self.files[self._current_index]
        if edit_mode:
            title = f" {filename}  [dim]^S Save  ^X Revert  BS on red: Restore  ^G File List[/dim]"
        else:
            del_tag = "[green]on[/green]" if self._show_deleted else "[red]off[/red]"
            title = f" {filename}  [dim]e Edit  ^R Del:{del_tag}[dim]  ^G List[/dim][/dim]"
        self.query_one("#editor-title", Static).update(title)

    def _reload_file_list(self) -> None:
        self.title = f"gitdiff  {self.branch_a} → {self._b_label}  (on {get_current_branch()})"
        self.query_one("#sidebar-title", Static).update(self._sidebar_title())

        tree = self.query_one("#file-list", Tree)
        self._build_file_tree(tree)

        first_leaf = self._first_leaf(tree.root)
        if first_leaf is not None:
            tree.move_cursor(first_leaf)
            self._current_index = first_leaf.data
            self._load_file(first_leaf.data)
        else:
            self.query_one("#diff-content", Static).update(
                "[dim]No differences between the selected branches.[/dim]"
            )
            self.query_one("#diff-title", Static).update(f" {self.branch_a}  →  {self._b_label}")
            self.query_one("#editor-view", Static).update("")
            self.query_one("#editor-title", Static).update(" Editor")

    def _render_diff(self, index: int) -> None:
        status, filename = self.files[index]
        _, badge, desc = STATUS_STYLES.get(status, ("white", "[?]", "Unknown"))
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        unstaged_tag = "  [yellow](unstaged)[/yellow]" if filename in self._unstaged else ""
        if not self.query_one("#comment-scroll").display:
            self.query_one("#diff-title", Static).update(
                f" {badge} {filename}  [{desc}]{unstaged_tag}"
            )
        content = self.query_one("#diff-content", Static)
        if diff_text:
            content.update(
                Syntax(diff_text, "diff", theme="monokai", line_numbers=True, word_wrap=False)
            )
        else:
            content.update("[dim]No textual diff (binary file or no changes)[/dim]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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


if __name__ == "__main__":
    main()
