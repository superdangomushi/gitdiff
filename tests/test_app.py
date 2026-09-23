"""Exercise the assembled panels without a terminal or network access."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Static

from gitdiff_tui.app import GitDiffApp
from gitdiff_tui.screens.branch import ChangeBranchScreen
from gitdiff_tui.widgets.editor import DiffTextArea
from gitdiff_tui.widgets.file_tree import FileTree
from gitdiff_tui.widgets.preview import EditorView
from test_diff import DIFF, review


class AppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.file = Path(directory.name) / "file.txt"
        self.file.write_text("first\nnew\nlast\n")
        for name, value in {
            "get_repo_root": directory.name,
            "get_current_branch": "feature",
            "get_unstaged_files": {"file.txt"},
            "get_file_diff": DIFF,
            "get_pr_review_threads": None,
        }.items():
            patcher = patch(f"gitdiff_tui.app.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = GitDiffApp("main", "", [("M", "file.txt")], {"file.txt": ("1", "1")})

    async def test_edit_restore_and_save(self):
        async with self.app.run_test(size=(150, 40)) as pilot:
            await pilot.press("e")
            editor = self.app.query_one("#editor", DiffTextArea)
            self.assertTrue(editor.display)
            self.assertEqual(editor.saved_text(), self.file.read_text())
            await pilot.press("ctrl+s")
            self.assertEqual(self.file.read_text(), "first\nnew\nlast\n")
            editor.move_cursor((1, 0))
            await pilot.press("x")
            self.assertEqual(editor.text.splitlines()[1], "old")
            await pilot.press("backspace", "ctrl+s")
            self.assertEqual(self.file.read_text(), "first\nold\nnew\nlast\n")
            await pilot.press("escape")
            self.assertFalse(editor.display)

    async def test_revert_and_panel_visibility(self):
        async with self.app.run_test(size=(150, 40)) as pilot:
            await pilot.press("e")
            editor = self.app.query_one("#editor", DiffTextArea)
            editor.move_cursor((0, 0))
            await pilot.press("x", "ctrl+x")
            self.assertEqual(editor.saved_text(), self.file.read_text())
            await pilot.press("ctrl+g", "ctrl+p")
            self.assertFalse(self.app.query_one("#editor-panel").display)
            self.assertFalse(self.app.query_one("#panel-splitter").display)
            await pilot.press("ctrl+f")
            self.assertTrue(self.app.query_one("#editor-panel").display)
            self.assertFalse(self.app.query_one("#diff-panel").display)
            await pilot.press("ctrl+f", "ctrl+p")
            self.assertTrue(self.app.query_one("#panel-splitter").display)

    async def test_reviews_remain_clickable_when_deletions_hidden(self):
        async with self.app.run_test(size=(150, 40)) as pilot:
            thread = review()
            self.app._apply_review_threads("feature", 42, {"file.txt": [thread]})
            view = self.app.query_one("#editor-view", EditorView)
            self.assertEqual(view.row_threads, {2: [thread]})
            await pilot.press("ctrl+r")
            self.assertEqual(view.row_threads, {1: [thread]})
            await pilot.click(view, offset=(3, 1))
            self.assertTrue(self.app.query_one("#comment-scroll").display)
            self.assertFalse(self.app.query_one("#diff-scroll").display)
            await pilot.press("escape")
            self.assertFalse(self.app.query_one("#comment-scroll").display)
            self.assertTrue(self.app.query_one("#diff-scroll").display)

    async def test_branch_dialog_and_empty_comparison(self):
        async with self.app.run_test(size=(150, 40)) as pilot:
            await pilot.press("b")
            self.assertIsInstance(self.app.screen, ChangeBranchScreen)
            self.app.screen.query_one("#input-a", Input).value = "base"
            self.app.screen.query_one("#input-b", Input).value = "target"
            with (
                patch("gitdiff_tui.app.check_ref", return_value=True),
                patch("gitdiff_tui.app.get_diff_files", return_value=([], None)),
                patch("gitdiff_tui.app.get_file_stats", return_value={}),
            ):
                await pilot.click("#btn-apply")
                await pilot.pause()
            self.assertEqual((self.app.branch_a, self.app.branch_b), ("base", "target"))
            self.assertEqual(self.app.files, [])
            self.assertIsNone(self.app.query_one("#file-list", FileTree).first_file())
            self.assertIn("No differences", str(self.app.query_one("#diff-content", Static).render()))

    async def test_file_tree_groups_paths_and_keeps_selection_indices(self):
        self.app.files = [("M", "z.txt"), ("A", "src/b.txt"), ("M", "src/a.txt")]
        async with self.app.run_test(size=(150, 40)) as pilot:
            tree = self.app.query_one("#file-list", FileTree)
            self.assertEqual(tree.first_file().data, 2)
            self.assertEqual([node.data for node in tree.root.children[0].children], [2, 1])
            tree.move_cursor(tree.first_file())
            await pilot.pause()
            await pilot.press("j")
            self.assertEqual(self.app._current_index, 1)
            tree.update_file_label(1, "A", "src/b.txt", ("3", "0"), True, 2)
            self.assertIn("+3", tree.cursor_node.label.plain)
