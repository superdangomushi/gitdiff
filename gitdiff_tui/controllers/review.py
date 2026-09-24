"""Fetching and displaying GitHub PR review comments."""

from textual import work
from textual.containers import ScrollableContainer
from textual.widgets import Static

from ..git import get_current_branch, get_file_diff
from ..github import get_pr_review_threads
from ..models import ReviewThread
from ..rendering import render_review_threads
from ..review_mapping import map_threads_to_buffer
from ..widgets.editor import DiffTextArea


class ReviewMixin:
    """Load PR review threads in the background and show them on demand."""

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
