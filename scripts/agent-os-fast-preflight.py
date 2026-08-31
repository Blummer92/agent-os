#!/usr/bin/env python3
"""Cheap deterministic preflight checks for changed repository files.

This module supplies early mechanical evidence only. It does not select focused
pytest suites, replace the authoritative aggregate, or grant any repository,
merge, closure, production, or external-write authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

CheckKind = Literal["python-compile", "json-parse", "yaml-parse"]
CheckStatus = Literal["passed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    path: str
    kind: CheckKind | None
    status: CheckStatus
    reason: str


@dataclass(frozen=True, slots=True)
class FastPreflightResult:
    checks: tuple[PreflightCheck, ...]
    passed: bool
    aggregate_required: Literal[True] = field(default=True, init=False)
    validation_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    closure_authorized: Literal[False] = field(default=False, init=False)
    production_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "checks": [
                {
                    "path": check.path,
                    "kind": check.kind,
                    "status": check.status,
                    "reason": check.reason,
                }
                for check in self.checks
            ],
            "passed": self.passed,
            "aggregate_required": True,
            "validation_authorized": False,
            "merge_authorized": False,
            "closure_authorized": False,
            "production_authorized": False,
            "external_write_authorized": False,
        }


def _normalize_relative_path(raw_path: str) -> str:
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("changed path must stay inside the repository")
    normalized = candidate.as_posix().lstrip("./")
    if not normalized or normalized == ".":
        raise ValueError("changed path must name a repository file")
    return normalized


def _check_file(repo_root: Path, relative_path: str) -> PreflightCheck:
    path = repo_root / relative_path
    suffix = path.suffix.lower()
    if suffix not in {".py", ".json", ".yml", ".yaml"}:
        return PreflightCheck(
            path=relative_path,
            kind=None,
            status="skipped",
            reason="no-admitted-cheap-check",
        )
    if not path.is_file():
        kind: CheckKind = {
            ".py": "python-compile",
            ".json": "json-parse",
            ".yml": "yaml-parse",
            ".yaml": "yaml-parse",
        }[suffix]
        return PreflightCheck(
            path=relative_path,
            kind=kind,
            status="failed",
            reason="changed-file-missing",
        )

    try:
        text = path.read_text(encoding="utf-8")
        if suffix == ".py":
            compile(text, relative_path, "exec")
            kind = "python-compile"
        elif suffix == ".json":
            json.loads(text)
            kind = "json-parse"
        else:
            yaml.safe_load(text)
            kind = "yaml-parse"
    except (OSError, UnicodeError, SyntaxError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return PreflightCheck(
            path=relative_path,
            kind=kind,
            status="failed",
            reason=f"{type(exc).__name__}: {exc}",
        )

    return PreflightCheck(
        path=relative_path,
        kind=kind,
        status="passed",
        reason="mechanical-check-passed",
    )


def run_fast_preflight(*, repo_root: str | Path, changed_files: tuple[str, ...]) -> FastPreflightResult:
    root = Path(repo_root).resolve()
    normalized = tuple(sorted({_normalize_relative_path(path) for path in changed_files}))
    checks = tuple(_check_file(root, path) for path in normalized)
    passed = all(check.status != "failed" for check in checks)
    return FastPreflightResult(checks=checks, passed=passed)
