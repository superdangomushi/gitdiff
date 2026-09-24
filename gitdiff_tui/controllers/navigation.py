"""Cursor movement, scrolling, and focus handling."""

from textual.containers import ScrollableContainer
from textual.widgets import Tree


class NavigationMixin:
    """Move through the file list and scroll the visible panel."""

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
