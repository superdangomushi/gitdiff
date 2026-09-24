"""Edit mode: loading, saving, and reverting the working-tree file."""

import os
from pathlib import Path

from ..diff import build_edit_buffer
from ..git import get_file_diff
from ..languages import get_language
from ..review_mapping import map_threads_to_buffer
from ..widgets.editor import DiffTextArea


class EditingMixin:
    """Enter/exit the editor and write changes back to disk."""

    def action_enter_edit(self) -> None:
        if not self.files:
            return
        status, _ = self.files[self._current_index]
        if status == "D":
            self.notify("Cannot edit a deleted file.", severity="warning")
            return
        self._enter_edit_mode()

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
