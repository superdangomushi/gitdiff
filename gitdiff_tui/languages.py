"""Filename extensions used to select editor syntax highlighting."""


from pathlib import Path
from typing import Optional


EXT_LANG: dict[str, str] = {
    ".py": "python",   ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx",     ".jsx": "javascript",
    ".sh": "bash",     ".bash": "bash",
    ".md": "markdown", ".json": "json",
    ".yaml": "yaml",   ".yml": "yaml",
    ".css": "css",     ".html": "html",     ".xml": "xml",
    ".go": "go",       ".rs": "rust",       ".c": "c",
    ".cpp": "cpp",     ".h": "c",           ".rb": "ruby",
    ".php": "php",     ".java": "java",     ".kt": "kotlin",
    ".sql": "sql",     ".toml": "toml",
}


def get_language(filename: str) -> Optional[str]:
    return EXT_LANG.get(Path(filename).suffix.lower())
