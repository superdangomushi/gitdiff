"""Map review threads to diff rows and editable buffer rows."""


from typing import Optional

from .diff import walk_diff
from .models import ReviewThread


def map_threads_to_diff(
    diff_text: str, threads: list["ReviewThread"]
) -> dict[int, list["ReviewThread"]]:
    """Map indices into ``parse_diff_lines(diff_text)`` to the threads on them."""
    right: dict[int, list[ReviewThread]] = {}
    left: dict[int, list[ReviewThread]] = {}
    for thread in threads:
        target = left if thread.side == "LEFT" else right
        for ln in thread.lines:
            target.setdefault(ln, []).append(thread)
    result: dict[int, list[ReviewThread]] = {}
    for i, (kind, _content, old, new) in enumerate(walk_diff(diff_text)):
        found = left.get(old, []) if kind == "del" else right.get(new, [])
        if found:
            result[i] = found
    return result


def map_threads_to_buffer(
    diff_text: str, deleted: set[int], line_count: int, threads: list["ReviewThread"]
) -> dict[int, list["ReviewThread"]]:
    """Map edit-buffer line indices (see ``build_edit_buffer``) to threads."""
    old_of_deleted = [old for kind, _c, old, _n in walk_diff(diff_text) if kind == "del"]
    deleted_rows = sorted(deleted)
    file_rows = [i for i in range(line_count) if i not in deleted]
    result: dict[int, list[ReviewThread]] = {}
    for thread in threads:
        for ln in thread.lines:
            row: Optional[int] = None
            if thread.side == "LEFT":
                if ln in old_of_deleted:
                    k = old_of_deleted.index(ln)
                    if k < len(deleted_rows):
                        row = deleted_rows[k]
            elif 0 < ln <= len(file_rows):
                row = file_rows[ln - 1]
            if row is not None:
                result.setdefault(row, []).append(thread)
    return result
