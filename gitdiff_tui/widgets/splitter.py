"""Draggable divider between two panels."""


from textual import events
from textual.widgets import Static


class PanelSplitter(Static):
    """Draggable vertical bar that resizes the diff and editor panels."""

    MIN_WIDTH = 10

    def __init__(self, left_id: str, right_id: str, **kwargs) -> None:
        super().__init__("", **kwargs)
        self._left_id = left_id
        self._right_id = right_id
        self._dragging = False

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.add_class("-dragging")
        self.capture_mouse()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._dragging:
            return
        left = self.app.query_one(f"#{self._left_id}")
        right = self.app.query_one(f"#{self._right_id}")
        start = left.region.x
        total = right.region.right - start - self.region.width
        if total <= self.MIN_WIDTH * 2:
            return
        width = max(self.MIN_WIDTH, min(event.screen_x - start, total - self.MIN_WIDTH))
        left.styles.width = f"{width}fr"
        right.styles.width = f"{total - width}fr"
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._dragging:
            self._dragging = False
            self.remove_class("-dragging")
            self.release_mouse()
            event.stop()
