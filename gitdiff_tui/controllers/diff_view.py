"""Rendering the selected file's diff and the read-only editor view."""

from rich.syntax import Syntax
from textual.widgets import Static

from ..diff import parse_diff_lines
from ..git import get_file_diff
from ..rendering import STATUS_STYLES, build_editor_view
from ..review_mapping import map_threads_to_diff
from ..widgets.preview import EditorView


class DiffViewMixin:
    """Load a file's diff into the diff panel and editor preview."""

    def action_toggle_deleted(self) -> None:
        self._show_deleted = not self._show_deleted
        label = "shown" if self._show_deleted else "hidden"
        self.notify(f"Deleted lines: {label}")
        self._refresh_editor_view()
        self._update_editor_title()

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
