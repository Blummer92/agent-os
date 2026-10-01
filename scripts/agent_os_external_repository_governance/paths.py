"""ERG declared-path safety (#581 owns executable normalization/containment).

A declared governance-document path must be relative to the repository root
and remain inside that root after normalization and symlink resolution.
Rejects, per the #580 standard: absolute paths, ``.``/``..`` segments,
backslashes, repeated separators, NUL-bearing paths, and paths that escape
through symlinks.

The lexical pattern is consumed from the #580 schema
(``$defs.safeRelativePath.pattern``), not redeclared here. Normalization,
containment, and symlink traversal are executable ERG2 checks.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path, PurePosixPath


class ErgPathError(ValueError):
    """A fail-closed declared-path violation (malformed input, not infrastructure)."""


def check_lexical(value: str, pattern: str) -> None:
    """Lexical check against the schema-owned safe-relative-path pattern."""
    if re.fullmatch(pattern, value) is None:
        raise ErgPathError(f"path {value!r} fails the schema safe-relative-path pattern")


def check_normalized_containment(value: str) -> str:
    """Executable normalization + containment. Returns the normalized path.

    The lexical check already forbids ``.``/``..`` segments, backslashes,
    repeated separators, absolute paths, and NUL bytes; this is the
    executable second line that proves the normalized form stays in-root.
    """
    normalized = posixpath.normpath(value)
    if normalized in (".", ""):
        raise ErgPathError(f"path {value!r} normalizes to the repository root itself")
    if normalized.startswith("../") or normalized == "..":
        raise ErgPathError(f"path {value!r} escapes the repository root after normalization")
    if ".." in PurePosixPath(normalized).parts:
        raise ErgPathError(f"path {value!r} contains a parent segment after normalization")
    return normalized


def check_symlink_containment(value: str, repo_root: Path) -> None:
    """Prove the declared path cannot escape the root through symlinks.

    Only meaningful when the referenced components exist; a declared path
    whose components do not exist has nothing to traverse and passes.
    Existence of the declared document itself is explicitly not evaluated
    (consumer repository behavior remains authoritative in the consumer).
    """
    root_real = os.path.realpath(repo_root)
    candidate = os.path.realpath(os.path.join(root_real, value))
    try:
        Path(candidate).relative_to(root_real)
    except ValueError:
        raise ErgPathError(
            f"path {value!r} escapes the repository root through a symlink"
        ) from None


def check_declared_path(
    value: object,
    *,
    schema_pattern: str,
    repo_root: Path | None,
    location: str,
) -> list[str]:
    """Run all ERG path checks for one declared path.

    Returns a list of violation details (empty when the path is safe).
    Non-string values are a schema-conformance violation, reported here as
    a path finding so the evidence stays with the declaration.
    """
    if not isinstance(value, str):
        return [f"{location}: declared path must be a string"]
    findings: list[str] = []
    try:
        check_lexical(value, schema_pattern)
    except ErgPathError as exc:
        return [f"{location}: {exc}"]
    try:
        check_normalized_containment(value)
    except ErgPathError as exc:
        return [f"{location}: {exc}"]
    if repo_root is not None:
        try:
            check_symlink_containment(value, repo_root)
        except ErgPathError as exc:
            findings.append(f"{location}: {exc}")
        except OSError as exc:
            findings.append(f"{location}: path containment could not be evaluated: {exc}")
    return findings
