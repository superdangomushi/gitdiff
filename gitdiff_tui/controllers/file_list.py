"""The changed-file sidebar and switching the compared branches."""

from textual.widgets import Static

from ..git import (
    check_ref, get_current_branch, get_diff_files, get_file_stats, get_unstaged_files,
)
from ..screens.branch import ChangeBranchScreen
from ..widgets.file_tree import FileTree


class FileListMixin:
    """Build and refresh the file tree for the current comparison."""

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
