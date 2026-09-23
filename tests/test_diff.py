"""Regression checks for diff rows, review anchors, and edit buffers."""

import unittest

from gitdiff_tui.diff import (
    build_edit_buffer, parse_deleted_lines, remap_line_indices, walk_diff,
)
from gitdiff_tui.models import ReviewThread
from gitdiff_tui.rendering import build_editor_view
from gitdiff_tui.review_mapping import map_threads_to_buffer, map_threads_to_diff


DIFF = """diff --git a/file.txt b/file.txt
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 first
-old
+new
 last
"""


def review(side="RIGHT", line=2, start_line=None):
    return ReviewThread("file.txt", side, line, start_line, False, False, DIFF)


class DiffTests(unittest.TestCase):
    def test_old_and_new_line_numbers(self):
        self.assertEqual(list(walk_diff(DIFF)), [
            ("ctx", "first", 1, 1), ("del", "old", 2, None),
            ("add", "new", None, 2), ("ctx", "last", 3, 3),
        ])

    def test_buffer_round_trip_preserves_file_and_final_newline(self):
        for content in ("first\nnew\nlast\n", "first\nnew\nlast"):
            with self.subTest(content=content):
                buffer, added, deleted = build_edit_buffer(content, DIFF)
                self.assertEqual(added, {2})
                self.assertEqual(deleted, {1})
                saved = "\n".join(
                    line for i, line in enumerate(buffer.split("\n"))
                    if i not in deleted
                )
                self.assertEqual(saved, content)

    def test_empty_new_range_restores_at_start(self):
        diff = "@@ -1,2 +0,0 @@\n-first\n-second\n"
        self.assertEqual(parse_deleted_lines(diff), [(0, "first"), (0, "second")])
        self.assertEqual(build_edit_buffer("", diff), ("first\nsecond\n", set(), {0, 1}))

    def test_markers_follow_inserted_and_removed_lines(self):
        self.assertEqual(remap_line_indices(["a", "b"], ["x", "a", "b"], {1}), {2})
        self.assertEqual(remap_line_indices(["a", "b"], ["a"], {1}), set())

    def test_review_anchors_on_both_sides_and_outdated_threads(self):
        left, right, outdated = review("LEFT"), review(), review(line=None)
        threads = [left, right, outdated]
        self.assertEqual(map_threads_to_diff(DIFF, threads), {1: [left], 2: [right]})
        self.assertEqual(
            map_threads_to_buffer(DIFF, {1}, 5, threads), {1: [left], 2: [right]},
        )

    def test_multiline_review(self):
        thread = review(line=3, start_line=1)
        self.assertEqual(map_threads_to_diff(DIFF, [thread]), {
            0: [thread], 2: [thread], 3: [thread],
        })

    def test_preview_can_hide_deleted_lines(self):
        rows = [(kind, content, new) for kind, content, _, new in walk_diff(DIFF)]
        visible = build_editor_view(rows, True, {2})
        hidden = build_editor_view(rows, False, {2})
        self.assertEqual(visible.plain, "1 first\n~ old\n2 new\n3 last\n")
        self.assertEqual(hidden.plain, "1 first\n2 new\n3 last\n")
        self.assertTrue(any(span.style == "black on yellow" for span in hidden.spans))
