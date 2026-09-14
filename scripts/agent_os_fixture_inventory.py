from __future__ import annotations

from pathlib import PurePosixPath


def select_exact_basename(paths: object, basename: str) -> tuple[str, ...]:
    """Return canonical paths whose final component exactly equals basename."""
    if not isinstance(paths, tuple):
        raise TypeError("paths must be a tuple")
    if not isinstance(basename, str) or not basename or "/" in basename or "\\" in basename:
        raise ValueError("basename must be one path component")
    selected: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
            raise ValueError("paths must contain canonical relative POSIX paths")
        parsed = PurePosixPath(path)
        if str(parsed) != path or ".." in parsed.parts:
            raise ValueError("paths must contain canonical relative POSIX paths")
        if parsed.name == basename:
            selected.append(path)
    return tuple(sorted(set(selected)))
