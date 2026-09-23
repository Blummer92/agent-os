from __future__ import annotations

import re

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class DeclaredPathError(ValueError):
    """Raised when a declared repository-relative path is lexically invalid."""

    def __init__(self, code: str, value: object) -> None:
        self.code = code
        self.value = value
        super().__init__(f"{code}: invalid declared path")


def normalize_declared_path(value: str) -> str:
    """Validate and return one canonical repository-relative POSIX path."""

    if not isinstance(value, str) or value == "":
        raise DeclaredPathError("empty", value)

    if value.startswith("\\\\"):
        raise DeclaredPathError("absolute-unc", value)

    if _WINDOWS_DRIVE.match(value):
        raise DeclaredPathError("absolute-windows-drive", value)

    if value.startswith("/"):
        raise DeclaredPathError("absolute-posix", value)

    if "\\" in value:
        raise DeclaredPathError("backslash", value)

    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DeclaredPathError("control-character", value)

    if value.startswith("./"):
        raise DeclaredPathError("noncanonical-dot-prefix", value)

    segments = value.split("/")

    if ".." in segments:
        raise DeclaredPathError("traversal", value)

    if value.endswith("/") or "" in segments or "." in segments:
        raise DeclaredPathError("noncanonical-separator", value)

    return value


def normalize_declared_pattern(value: str) -> str:
    """Validate the bounded declared-pattern grammar and preserve its text."""

    normalized = normalize_declared_path(value)

    if "**" in normalized:
        raise DeclaredPathError("unsupported-double-star", value)
    if "?" in normalized:
        raise DeclaredPathError("unsupported-question-mark", value)
    if "[" in normalized or "]" in normalized:
        raise DeclaredPathError("unsupported-bracket-class", value)

    return normalized


def declared_path_matches(path: str, pattern: str) -> bool:
    """Match a validated path using literal or segment-local wildcard rules."""

    normalized_path = normalize_declared_path(path)
    normalized_pattern = normalize_declared_pattern(pattern)

    if "*" not in normalized_pattern:
        return normalized_path == normalized_pattern or normalized_path.startswith(
            f"{normalized_pattern}/"
        )

    expression = "^" + re.escape(normalized_pattern).replace(r"\*", "[^/]*") + "$"
    return re.fullmatch(expression, normalized_path) is not None
