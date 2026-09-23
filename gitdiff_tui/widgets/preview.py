"""Read-only diff preview with clickable review comments."""


from textual import events
from textual.widgets import Static

from ..models import ReviewThread


class EditorView(Static):
    """Read-only diff view; clicking a yellow (commented) line opens its threads."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.row_threads: dict[int, list[ReviewThread]] = {}

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is not None and offset.y in self.row_threads:
            self.app.show_review_threads(self.row_threads[offset.y])
