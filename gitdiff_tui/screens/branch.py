"""Dialog for changing the comparison branches."""


from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ChangeBranchScreen(ModalScreen):
    """Modal screen for changing comparison branches."""

    CSS_PATH = "../styles/branch.tcss"

    def __init__(self, branch_a: str, branch_b: str) -> None:
        super().__init__()
        self.current_a = branch_a
        self.current_b = branch_b

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Change Comparison Branches", id="dialog-title")
            yield Label("Branch A:", classes="branch-label")
            yield Input(value=self.current_a, id="input-a", placeholder="branch-a")
            yield Label("Branch B:", classes="branch-label")
            yield Input(value=self.current_b, id="input-b", placeholder="branch-b")
            with Horizontal(id="button-row"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Apply", variant="primary", id="btn-apply")

    def on_mount(self) -> None:
        self.query_one("#input-a", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-apply":
            self._apply()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._apply()

    def _apply(self) -> None:
        a = self.query_one("#input-a", Input).value.strip()
        b = self.query_one("#input-b", Input).value.strip()
        if a and b:
            self.dismiss((a, b))
