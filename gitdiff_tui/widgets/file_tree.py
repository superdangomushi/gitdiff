"""File hierarchy, labels, and navigation for the sidebar."""

from typing import Optional

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ..rendering import file_leaf_label


class FileTree(Tree[int]):
    """Group changed files by directory while preserving their source indices."""

    def __init__(self, **kwargs) -> None:
        super().__init__("Files", **kwargs)
        self.show_root = False
        self.guide_depth = 2
        self._leaf_nodes: dict[int, TreeNode] = {}

    def set_files(
        self,
        files: list[tuple[str, str]],
        stats: dict[str, tuple[str, str]],
        unstaged: set[str],
        comment_counts: dict[str, int],
    ) -> None:
        self.clear()
        self.root.expand()
        self._leaf_nodes = {}
        dir_nodes: dict[tuple[str, ...], TreeNode] = {(): self.root}
        indexed = sorted(enumerate(files), key=lambda item: item[1][1].split("/"))

        for index, (status, filename) in indexed:
            parts = filename.split("/")
            for depth in range(1, len(parts)):
                key = tuple(parts[:depth])
                if key not in dir_nodes:
                    dir_nodes[key] = dir_nodes[key[:-1]].add(
                        f"[bold]{parts[depth - 1]}/[/bold]", expand=True
                    )
            parent = dir_nodes[tuple(parts[:-1])]
            label = file_leaf_label(
                status, parts[-1], stats.get(filename, ("-", "-")),
                filename in unstaged, comment_counts.get(filename, 0),
            )
            self._leaf_nodes[index] = parent.add_leaf(label, data=index)

    def update_file_label(
        self, index: int, status: str, filename: str,
        stats: tuple[str, str], unstaged: bool, comments: int,
    ) -> None:
        node = self._leaf_nodes.get(index)
        if node is not None:
            node.set_label(file_leaf_label(
                status, filename.split("/")[-1], stats, unstaged, comments,
            ))

    def first_file(self) -> Optional[TreeNode]:
        """Return the first file in the displayed path order, if any."""
        return next(iter(self._leaf_nodes.values()), None)
