#!/usr/bin/env python3
"""gitdiff - Interactive git branch diff viewer"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import (
    Header, Footer, ListView, ListItem, Label, Static, Input, Button, TextArea
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
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
# Diff parsing & rendering
# ---------------------------------------------------------------------------

def parse_diff_lines(diff_text: str) -> list[tuple[str, str, Optional[int]]]:
    """Parse diff text into (kind, content, new_lineno) tuples.

    kind     : 'add' | 'del' | 'ctx'
    new_lineno: 1-based line number in the new file; None for deleted lines.
    """
    result: list[tuple[str, str, Optional[int]]] = []
    new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ")):
            in_hunk = False
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            if m:
                new_lineno = int(m.group(1)) - 1
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("+"):
            new_lineno += 1
            result.append(("add", line[1:], new_lineno))
        elif line.startswith("-"):
            result.append(("del", line[1:], None))
        else:  # context line (starts with space)
            new_lineno += 1
            result.append(("ctx", line[1:], new_lineno))

    return result


def build_editor_view(
    diff_lines: list[tuple[str, str, Optional[int]]],
    show_deleted: bool,
) -> RichText:
    """Build Rich Text with green/red diff highlights and line numbers."""
    text = RichText()
    line_nums = [ln for _, _, ln in diff_lines if ln is not None]
    width = len(str(max(line_nums))) if line_nums else 1

    for kind, content, lineno in diff_lines:
        if kind == "del" and not show_deleted:
            continue
        gutter = f"{lineno:>{width}} " if lineno is not None else f"{'~':>{width}} "
        if kind == "add":
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


class DiffTextArea(TextArea):
    """TextArea that highlights added/deleted lines with green/red backgrounds."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._added_lines: set[int] = set()   # 0-based line indices → green
        self._deleted_lines: set[int] = set() # 0-based line indices → red

    def set_diff_lines(self, added: set[int], deleted: set[int]) -> None:
        self._added_lines = added
        self._deleted_lines = deleted
        self.refresh()

    def on_key(self, event) -> None:
        """Capture Tab for indentation and Escape to exit edit mode."""
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self.insert("\t")
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.action_exit_edit()

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        doc_y = y + int(self.scroll_y)
        if doc_y in self._added_lines:
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


class FileListItem(ListItem):
    def __init__(self, index: int, status: str, filename: str, stats: tuple[str, str]) -> None:
        super().__init__()
        self.file_index = index
        self.status = status
        self.filename = filename
        self.stats = stats

    def compose(self) -> ComposeResult:
        color, badge, _ = STATUS_STYLES.get(self.status, ("white", "[?]", "Unknown"))
        added, removed = self.stats
        if added != "-":
            stats_str = f"  [green]+{added}[/green] [red]-{removed}[/red]"
        else:
            stats_str = ""
        yield Label(f"[{color}]{badge}[/{color}] {self.filename}{stats_str}")


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
    }

    ListItem {
        padding: 0 1;
    }

    #diff-panel {
        width: 1fr;
        border-right: solid $primary-darken-2;
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
        Binding("ctrl+s", "write_out",       "Write Out",    priority=True),
        Binding("ctrl+x", "revert_file",     "Revert",       priority=True),
        Binding("escape", "exit_edit",        "Exit Edit",    priority=True),
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

    @property
    def _b_label(self) -> str:
        return self.branch_b if self.branch_b else "Working Tree"
        self._show_editor: bool = True
        self._diff_lines: list[tuple[str, str, Optional[int]]] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static(f" Files ({len(self.files)})", id="sidebar-title")
                items = [
                    FileListItem(i, status, filename, self.file_stats.get(filename, ("-", "-")))
                    for i, (status, filename) in enumerate(self.files)
                ]
                yield ListView(*items, id="file-list")
            with Vertical(id="diff-panel"):
                yield Static(f" {self.branch_a}  →  {self._b_label}", id="diff-title")
                with ScrollableContainer(id="diff-scroll"):
                    yield Static("← Select a file", id="diff-content")
            with Vertical(id="editor-panel"):
                yield Static(" Editor", id="editor-title")
                with ScrollableContainer(id="editor-view-scroll"):
                    yield Static("← Select a file", id="editor-view")
                yield DiffTextArea("", id="editor", show_line_numbers=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"gitdiff  {self.branch_a} → {self._b_label}"
        self.query_one("#file-list", ListView).focus()
        if self.files:
            self._load_file(0)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, FileListItem):
            self._current_index = event.item.file_index
            self._load_file(event.item.file_index)

    def action_move_down(self) -> None:
        self.query_one("#file-list", ListView).action_cursor_down()

    def action_move_up(self) -> None:
        self.query_one("#file-list", ListView).action_cursor_up()

    def action_page_down(self) -> None:
        self.query_one("#diff-scroll", ScrollableContainer).scroll_page_down()

    def action_page_up(self) -> None:
        self.query_one("#diff-scroll", ScrollableContainer).scroll_page_up()

    def action_exit_edit(self) -> None:
        if self.query_one("#editor").display:
            self._exit_edit_mode()

    def action_focus_list(self) -> None:
        self._exit_edit_mode()
        self.query_one("#file-list", ListView).focus()

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
        panel = self.query_one("#editor-panel")
        panel.display = self._show_editor
        if not self._show_editor:
            # If hiding while in edit mode, exit edit mode first
            if self.query_one("#editor").display:
                self._exit_edit_mode()
            self.query_one("#file-list", ListView).focus()

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
            Path(filepath).write_text(editor.text, encoding="utf-8")
            self.notify(f"Saved: {filename}")
            # Refresh diff, view, and editor highlights after save
            diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
            self._diff_lines = parse_diff_lines(diff_text)
            self._render_diff(self._current_index)
            self._refresh_editor_view()
            editor.set_diff_lines(*self._compute_editor_highlights())
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
        self.query_one("#editor", DiffTextArea).load_text(content)
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
            self._reload_file_list()

        self.push_screen(ChangeBranchScreen(self.branch_a, self.branch_b), on_dismiss)

    # ---- internal helpers ----

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
        editor.load_text(content)
        editor.set_diff_lines(*self._compute_editor_highlights())
        self.query_one("#editor-view-scroll").display = False
        editor.display = True
        editor.focus()
        self._update_editor_title(edit_mode=True)

    def _compute_editor_highlights(self) -> tuple[set[int], set[int]]:
        """Return (added_lines, deleted_lines) as 0-based index sets for the editor."""
        added: set[int] = set()
        # deleted lines don't exist in the actual file, so nothing to mark
        for kind, _content, lineno in self._diff_lines:
            if kind == "add" and lineno is not None:
                added.add(lineno - 1)  # convert 1-based to 0-based
        return added, set()

    def _exit_edit_mode(self) -> None:
        self.query_one("#editor").display = False
        self.query_one("#editor-view-scroll").display = True
        self._update_editor_title(edit_mode=False)

    def _load_file(self, index: int) -> None:
        self._render_diff(index)
        status, filename = self.files[index]
        if status == "D" or self._repo_root is None:
            self._diff_lines = []
            self.query_one("#editor-view", Static).update("[dim](deleted file)[/dim]")
            self.query_one("#editor-title", Static).update(" Editor  [dim](deleted)[/dim]")
            return
        diff_text = get_file_diff(self.branch_a, self.branch_b, filename)
        self._diff_lines = parse_diff_lines(diff_text)
        self._refresh_editor_view()
        self._update_editor_title()

    def _refresh_editor_view(self) -> None:
        view = self.query_one("#editor-view", Static)
        if self._diff_lines:
            view.update(build_editor_view(self._diff_lines, self._show_deleted))
        else:
            view.update("[dim]No diff data available.[/dim]")

    def _update_editor_title(self, edit_mode: bool = False) -> None:
        if not self.files:
            return
        _, filename = self.files[self._current_index]
        if edit_mode:
            title = f" {filename}  [dim]^S Save  ^X Revert  ^G File List[/dim]"
        else:
            del_tag = "[green]on[/green]" if self._show_deleted else "[red]off[/red]"
            title = f" {filename}  [dim]e Edit  ^R Del:{del_tag}[dim]  ^G List[/dim][/dim]"
        self.query_one("#editor-title", Static).update(title)

    def _reload_file_list(self) -> None:
        self.title = f"gitdiff  {self.branch_a} → {self._b_label}"
        self.query_one("#sidebar-title", Static).update(f" Files ({len(self.files)})")

        list_view = self.query_one("#file-list", ListView)
        list_view.clear()
        for i, (status, filename) in enumerate(self.files):
            list_view.append(
                FileListItem(i, status, filename, self.file_stats.get(filename, ("-", "-")))
            )

        if self.files:
            self._load_file(0)
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
        self.query_one("#diff-title", Static).update(f" {badge} {filename}  [{desc}]")
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

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: gitdiff <branch-a> [<branch-b>]")
        print()
        print("  <branch-b> omitted  → compare with working tree (uncommitted changes)")
        print()
        print("  Interactively browse and edit diffs between two branches.")
        print("  j/k      move file list     Ctrl+D/U  scroll diff")
        print("  e        enter edit mode    Ctrl+G    back to file list")
        print("  Ctrl+S   save file          Ctrl+X    revert file")
        print("  Ctrl+R   toggle deleted     Ctrl+P    toggle editor panel")
        print("  b        change branches")
        print("  q        quit")
        sys.exit(1)

    branch_a = sys.argv[1]
    branch_b = sys.argv[2] if len(sys.argv) >= 3 else ""

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
