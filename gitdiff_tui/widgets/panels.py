"""Composition of the file, diff, and editor panels."""

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Static

from .editor import DiffTextArea
from .file_tree import FileTree
from .preview import EditorView


class FilePanel(Vertical):
    """Sidebar containing a title and the changed-file tree."""

    def __init__(self, title: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="sidebar-title")
        yield FileTree(id="file-list")


class DiffPanel(Vertical):
    """Diff summary and review comments occupying the same panel."""

    def __init__(self, title: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="diff-title")
        with ScrollableContainer(id="diff-scroll"):
            yield Static("← Select a file", id="diff-content")
        with ScrollableContainer(id="comment-scroll"):
            yield Static("", id="comment-content")


class EditorPanel(Vertical):
    """Read-only preview and editable buffer occupying the same panel."""

    def compose(self) -> ComposeResult:
        yield Static(" Editor", id="editor-title")
        with ScrollableContainer(id="editor-view-scroll"):
            yield EditorView("← Select a file", id="editor-view")
        yield DiffTextArea("", id="editor", show_line_numbers=True)
