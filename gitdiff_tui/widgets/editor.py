"""Editable diff buffer with deletion protection and review highlights."""


from typing import Optional

from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import events
from textual.geometry import Offset
from textual.strip import Strip
from textual.widgets import TextArea

from ..diff import remap_line_indices
from ..models import ReviewThread


_ADD_BG = RichStyle(bgcolor="dark_green")


_DEL_BG = RichStyle(bgcolor="dark_red")


_COMMENT_BG = RichStyle(color="black", bgcolor="yellow")


_REMAP_DEBOUNCE = 0.1  # seconds to wait after a keystroke before re-anchoring


class DiffTextArea(TextArea):
    """TextArea that highlights added/deleted lines with green/red backgrounds.

    Deleted lines are shown inline but are not part of the file: they are
    read-only, dropped on save, and Backspace on one restores it.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._added_lines: set[int] = set()   # 0-based line indices → green
        self._deleted_lines: set[int] = set() # 0-based line indices → red
        self._anchor_lines: list[str] = []    # buffer contents the indices refer to
        self._comment_rows: dict[int, list[ReviewThread]] = {}  # → yellow, clickable
        self._remap_timer = None

    def set_diff_lines(self, added: set[int], deleted: set[int]) -> None:
        if self._remap_timer is not None:
            self._remap_timer.stop()
            self._remap_timer = None
        self._added_lines = set(added)
        self._deleted_lines = set(deleted)
        self._anchor_lines = self.text.split("\n")
        self.refresh()

    def set_comment_rows(self, rows: dict[int, list["ReviewThread"]]) -> None:
        """Set comment rows; call right after ``set_diff_lines`` (same anchor)."""
        self._comment_rows = dict(rows)
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        """Clicking a commented (yellow) line shows its review threads."""
        if not self._comment_rows:
            return
        offset = event.get_content_offset(self)
        if offset is None:
            return
        self._sync_diff_lines()
        row = self._document_row(offset.y)
        if row in self._comment_rows:
            self.app.show_review_threads(self._comment_rows[row])

    def on_key(self, event) -> None:
        """Capture Tab for indentation and Escape to exit edit mode."""
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            if not self._touches_deleted(*self.selection):
                self.insert("\t")
        elif event.key == "escape":
            event.stop()
            event.prevent_default()
            self.app.action_exit_edit()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Re-anchor the highlights after the buffer is edited."""
        if not self._added_lines and not self._deleted_lines and not self._comment_rows:
            return
        if self._remap_timer is not None:
            self._remap_timer.stop()
        self._remap_timer = self.set_timer(_REMAP_DEBOUNCE, self._remap_diff_lines)

    def _sync_diff_lines(self) -> None:
        """Re-anchor the highlights now instead of waiting for the debounce."""
        if self._remap_timer is not None:
            self._remap_timer.stop()
        self._remap_diff_lines()

    def saved_text(self) -> str:
        """Buffer contents without the (unrestored) deleted lines."""
        self._sync_diff_lines()
        return "\n".join(
            line for i, line in enumerate(self.text.split("\n"))
            if i not in self._deleted_lines
        )

    def _touches_deleted(self, start, end) -> bool:
        if not self._deleted_lines:
            return False
        self._sync_diff_lines()
        top, bottom = sorted((start[0], end[0]))
        return any(top <= row <= bottom for row in self._deleted_lines)

    def action_delete_left(self) -> None:
        """Backspace on a deleted (red) line restores it instead of editing."""
        if self.selection.is_empty and self._deleted_lines:
            self._sync_diff_lines()
            row = self.cursor_location[0]
            if row in self._deleted_lines:
                self._deleted_lines.discard(row)
                self.refresh()
                return
        super().action_delete_left()

    def _delete_via_keyboard(self, start, end):
        if self._touches_deleted(start, end):
            self.notify("Deleted line: press Backspace to restore it first.",
                        severity="warning")
            return None
        return super()._delete_via_keyboard(start, end)

    def _replace_via_keyboard(self, insert, start, end):
        if self._touches_deleted(start, end):
            self.notify("Deleted line: press Backspace to restore it first.",
                        severity="warning")
            return None
        return super()._replace_via_keyboard(insert, start, end)

    def _remap_diff_lines(self) -> None:
        self._remap_timer = None
        new_lines = self.text.split("\n")
        if new_lines == self._anchor_lines:
            return
        self._added_lines = remap_line_indices(
            self._anchor_lines, new_lines, self._added_lines
        )
        self._deleted_lines = remap_line_indices(
            self._anchor_lines, new_lines, self._deleted_lines
        )
        comment_rows: dict[int, list[ReviewThread]] = {}
        for row, threads in self._comment_rows.items():
            for new_row in remap_line_indices(self._anchor_lines, new_lines, {row}):
                comment_rows[new_row] = threads
        self._comment_rows = comment_rows
        self._anchor_lines = new_lines
        self.refresh()

    def _document_row(self, y: int) -> Optional[int]:
        """Map a screen row to the document line it renders.

        A soft-wrapped line occupies several screen rows, so the row index is
        not the line index; ``scroll_offset`` is also the integer offset the
        base widget actually renders with, unlike the animated ``scroll_y``.
        """
        y_offset = y + self.scroll_offset.y
        if y_offset < 0:
            return None
        wrapped = getattr(self, "wrapped_document", None)
        if wrapped is None:  # Textual too old to soft wrap: rows are lines
            return y_offset if y_offset < self.document.line_count else None
        if y_offset >= wrapped.height:
            return None  # padding below the last line
        return wrapped.offset_to_location(Offset(0, y_offset))[0]

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        doc_y = self._document_row(y)
        if doc_y is None:
            return strip
        if doc_y in self._comment_rows:
            bg = _COMMENT_BG
        elif doc_y in self._added_lines:
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
