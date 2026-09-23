"""Review comment data shared by services, diff mapping, and the UI."""


from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReviewComment:
    author: str
    body: str
    created_at: str


@dataclass
class ReviewThread:
    path: str
    side: str             # 'RIGHT' (new file) | 'LEFT' (old file)
    line: Optional[int]   # None when the thread is outdated
    start_line: Optional[int]
    resolved: bool
    outdated: bool
    diff_hunk: str
    comments: list[ReviewComment] = field(default_factory=list)

    @property
    def lines(self) -> range:
        if self.line is None:
            return range(0)
        return range(self.start_line or self.line, self.line + 1)
