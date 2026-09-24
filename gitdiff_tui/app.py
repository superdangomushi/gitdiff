"""Application state and coordination between repository services and UI panels."""


from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from .controllers import (
    DiffViewMixin, EditingMixin, FileListMixin, LayoutMixin, NavigationMixin, ReviewMixin,
)
from .git import get_current_branch, get_repo_root
from .models import ReviewThread
from .widgets.file_tree import FileTree
from .widgets.panels import DiffPanel, EditorPanel, FilePanel
from .widgets.splitter import PanelSplitter


class GitDiffApp(
    NavigationMixin, LayoutMixin, EditingMixin, FileListMixin, DiffViewMixin, ReviewMixin, App
):
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
