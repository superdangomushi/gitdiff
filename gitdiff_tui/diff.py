"""Pure diff parsing, edit-buffer construction, and line tracking."""


import difflib
import re
from typing import Iterator, Optional


def _hunk_offset(header: str, default: int, sign: str = "+") -> int:
    """Return the number of new-file (``sign='+'``) or old-file (``'-'``)
    lines that precede a hunk.

    ``@@ -a,b +c,d @@`` starts at line ``c``, except that an empty new range
    (``d == 0``) names the line the hunk comes *after*.
    """
    m = re.search(re.escape(sign) + r"(\d+)(?:,(\d+))?", header)
    if not m:
        return default
    start = int(m.group(1))
    return start if m.group(2) == "0" else start - 1


def _hunk_new_offset(header: str, default: int) -> int:
    return _hunk_offset(header, default, "+")


def walk_diff(diff_text: str) -> Iterator[tuple[str, str, Optional[int], Optional[int]]]:
    """Yield (kind, content, old_lineno, new_lineno) for every hunk line.

    kind: 'add' | 'del' | 'ctx'. Line numbers are 1-based; the side a line
    does not exist on is None.
    """
    old_lineno = new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ")):
            in_hunk = False
            continue
        if line.startswith("@@"):
            old_lineno = _hunk_offset(line, old_lineno, "-")
            new_lineno = _hunk_offset(line, new_lineno, "+")
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("+"):
            new_lineno += 1
            yield "add", line[1:], None, new_lineno
        elif line.startswith("-"):
            old_lineno += 1
            yield "del", line[1:], old_lineno, None
        else:  # context line (starts with space)
            old_lineno += 1
            new_lineno += 1
            yield "ctx", line[1:], old_lineno, new_lineno


def parse_diff_lines(diff_text: str) -> list[tuple[str, str, Optional[int]]]:
    """Parse diff text into (kind, content, new_lineno) tuples.

    kind     : 'add' | 'del' | 'ctx'
    new_lineno: 1-based line number in the new file; None for deleted lines.
    """
    return [(kind, content, new) for kind, content, _old, new in walk_diff(diff_text)]


def parse_deleted_lines(diff_text: str) -> list[tuple[int, str]]:
    """Return (anchor, content) for every deleted line in the diff.

    anchor: how many new-file lines precede the deleted line, i.e. the 0-based
    index in the new file it would be restored in front of.
    """
    result: list[tuple[int, str]] = []
    new_lineno = 0
    in_hunk = False

    for line in diff_text.splitlines():
        if line.startswith(("diff ", "index ", "--- ", "+++ ")):
            in_hunk = False
            continue
        if line.startswith("@@"):
            new_lineno = _hunk_new_offset(line, new_lineno)
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\"):
            continue
        if line.startswith("-"):
            result.append((new_lineno, line[1:]))
        else:
            new_lineno += 1

    return result


def build_edit_buffer(
    content: str,
    diff_text: str,
) -> tuple[str, set[int], set[int]]:
    """Interleave the diff's deleted lines into ``content`` for editing.

    Returns (buffer, added, deleted): 0-based buffer line indices of the
    added lines (green) and of the inserted deleted lines (red).
    """
    file_lines = content.split("\n")
    added_new = {
        lineno - 1
        for kind, _content, lineno in parse_diff_lines(diff_text)
        if kind == "add" and lineno is not None
    }
    deletions = parse_deleted_lines(diff_text)

    lines: list[str] = []
    added: set[int] = set()
    deleted: set[int] = set()
    d = 0
    for i, line in enumerate(file_lines):
        while d < len(deletions) and deletions[d][0] <= i:
            deleted.add(len(lines))
            lines.append(deletions[d][1])
            d += 1
        if i in added_new:
            added.add(len(lines))
        lines.append(line)
    # Deletions past the end of the file (e.g. content no longer on disk)
    # go before the empty string that a trailing newline splits into.
    tail = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
    for _anchor, text in deletions[d:]:
        deleted.add(tail)
        lines.insert(tail, text)
        tail += 1

    return "\n".join(lines), added, deleted


def remap_line_indices(
    old_lines: list[str],
    new_lines: list[str],
    indices: set[int],
) -> set[int]:
    """Carry 0-based line indices from ``old_lines`` over to ``new_lines``.

    Lines that survived the edit keep their marker at the shifted position;
    lines that were removed lose it.
    """
    if not indices:
        return set()
    if old_lines == new_lines:
        return set(indices)

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    moved: set[int] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag not in ("equal", "replace"):
            continue  # 'insert' has no old lines, 'delete' has no new ones
        for i in indices:
            if not i1 <= i < i2:
                continue
            j = j1 + (i - i1)
            if j < j2:  # a shrinking 'replace' can drop the tail
                moved.add(j)
    return moved
