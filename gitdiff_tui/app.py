"""Application state and coordination between repository services and UI panels."""


import os
from pathlib import Path
from typing import Optional

from rich.syntax import Syntax
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer
from textual.widgets import Footer, Header, Static, Tree

from .diff import build_edit_buffer, parse_diff_lines
from .git import (
    check_ref, get_current_branch, get_diff_files, get_file_diff,
    get_file_stats, get_repo_root, get_unstaged_files,
)
from .github import get_pr_review_threads
from .languages import get_language
from .models import ReviewThread
from .rendering import STATUS_STYLES, build_editor_view, render_review_threads
from .review_mapping import map_threads_to_buffer, map_threads_to_diff
from .screens.branch import ChangeBranchScreen
from .widgets.editor import DiffTextArea
from .widgets.file_tree import FileTree
from .widgets.panels import DiffPanel, EditorPanel, FilePanel
from .widgets.preview import EditorView
from .widgets.splitter import PanelSplitter


class GitDiffApp(App):
    """Own comparison state and route user actions to services and widgets."""

    CSS_PATH = "styles/app.tcss"

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
            yield FilePanel(self._sidebar_title(), id="sidebar")
            yield DiffPanel(f" {self.branch_a}  →  {self._b_label}", id="diff-panel")
            yield PanelSplitter("diff-panel", "editor-panel", id="panel-splitter")
            yield EditorPanel(id="editor-panel")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"gitdiff  {self.branch_a} → {self._b_label}  (on {get_current_branch()})"
        tree = self.query_one("#file-list", FileTree)
        self._build_file_tree(tree)
        tree.focus()
        first_leaf = tree.first_file()
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
        for index in range(len(self.files)):
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
        status, filename = self.files[index]
        stats = self.file_stats.get(filename, ("-", "-"))
        self.query_one("#file-list", FileTree).update_file_label(
            index, status, filename, stats, filename in self._unstaged,
            len(self._pr_threads.get(filename, [])),
        )

    def _build_file_tree(self, tree: FileTree) -> None:
        self._refresh_unstaged()
        tree.set_files(
            self.files, self.file_stats, self._unstaged,
            {path: len(threads) for path, threads in self._pr_threads.items()},
        )

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

        tree = self.query_one("#file-list", FileTree)
        self._build_file_tree(tree)

        first_leaf = tree.first_file()
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
