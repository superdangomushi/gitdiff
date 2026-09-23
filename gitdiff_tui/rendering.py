"""Rich renderables and shared presentation styles."""


from typing import Optional

from rich.console import Group
from rich.markdown import Markdown
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text as RichText

from .models import ReviewThread


STATUS_STYLES: dict[str, tuple[str, str, str]] = {
    "A": ("green",   "[+]", "Added"),
    "M": ("yellow",  "[~]", "Modified"),
    "D": ("red",     "[-]", "Deleted"),
    "R": ("cyan",    "[→]", "Renamed"),
    "C": ("blue",    "[©]", "Copied"),
    "T": ("magenta", "[T]", "Type changed"),
}


_COMMENT_STYLE = "black on yellow"


def render_review_threads(threads: list["ReviewThread"]) -> Group:
    parts = []
    for thread in threads:
        where = f"{thread.path}:{thread.line}"
        tags = ""
        if thread.resolved:
            tags += "  [green](resolved)[/green]"
        if thread.outdated:
            tags += "  [dim](outdated)[/dim]"
        parts.append(RichText.from_markup(f"[bold yellow]{where}[/bold yellow]{tags}"))
        hunk = "\n".join(thread.diff_hunk.splitlines()[-4:])
        if hunk:
            parts.append(Syntax(hunk, "diff", theme="monokai", word_wrap=True))
        for comment in thread.comments:
            date = comment.created_at.replace("T", " ").rstrip("Z")
            parts.append(RichText.from_markup(
                f"\n[bold cyan]@{comment.author}[/bold cyan]  [dim]{date}[/dim]"
            ))
            parts.append(Markdown(comment.body))
        parts.append(Rule(style="dim"))
    return Group(*parts)


def build_editor_view(
    diff_lines: list[tuple[str, str, Optional[int]]],
    show_deleted: bool,
    commented: frozenset[int] | set[int] = frozenset(),
) -> RichText:
    """Build Rich Text with green/red diff highlights and line numbers.

    Lines whose index is in ``commented`` (PR review comments) are yellow.
    """
    text = RichText()
    line_nums = [ln for _, _, ln in diff_lines if ln is not None]
    width = len(str(max(line_nums))) if line_nums else 1

    for i, (kind, content, lineno) in enumerate(diff_lines):
        if kind == "del" and not show_deleted:
            continue
        gutter = f"{lineno:>{width}} " if lineno is not None else f"{'~':>{width}} "
        if i in commented:
            text.append(gutter + content + "\n", style=_COMMENT_STYLE)
        elif kind == "add":
            text.append(gutter + content + "\n", style="on dark_green")
        elif kind == "del":
            text.append(gutter + content + "\n", style="on dark_red")
        else:
            text.append(gutter + content + "\n")

    return text


def file_leaf_label(
    status: str, name: str, stats: tuple[str, str], unstaged: bool = False,
    comments: int = 0,
) -> str:
    color, badge, _ = STATUS_STYLES.get(status, ("white", "[?]", "Unknown"))
    added, removed = stats
    stats_str = f"  [green]+{added}[/green] [red]-{removed}[/red]" if added != "-" else ""
    name_str = f"[yellow]{name}[/yellow]" if unstaged else name
    comment_str = f"  [black on yellow] {comments} [/black on yellow]" if comments else ""
    return f"[{color}]{badge}[/{color}] {name_str}{stats_str}{comment_str}"
