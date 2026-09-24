"""Showing and hiding the diff and editor panels."""

from textual.widgets import Tree


class LayoutMixin:
    """Toggle panel visibility and keep the splitter in sync."""

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

    def _update_splitter(self) -> None:
        # The splitter only makes sense while both the diff and editor panels are shown.
        self.query_one("#panel-splitter").display = (
            self.query_one("#diff-panel").display and self.query_one("#editor-panel").display
        )
