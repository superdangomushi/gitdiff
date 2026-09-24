"""Behaviour of ``GitDiffApp`` split into mixins by responsibility."""

from .diff_view import DiffViewMixin
from .editing import EditingMixin
from .file_list import FileListMixin
from .layout import LayoutMixin
from .navigation import NavigationMixin
from .review import ReviewMixin

__all__ = [
    "DiffViewMixin", "EditingMixin", "FileListMixin",
    "LayoutMixin", "NavigationMixin", "ReviewMixin",
]
