"""Fail-closed runtime dependency parity check for execution-service validation.

This helper is intentionally package-local validation tooling. It derives the
supported dependency range from the execution-service ``pyproject.toml`` and
compares it with the active Python runtime before package tests import MCP-facing
modules. It installs nothing and creates no environment-management authority.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as installed_version
from pathlib import Path
import tomllib
from typing import Callable

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

PROJECT_FILE = Path(__file__).with_name("pyproject.toml")


class RuntimeDependencyMismatch(RuntimeError):
    """Raised when the active runtime cannot satisfy canonical package metadata."""


def declared_requirement(
    package_name: str,
    *,
    project_file: Path = PROJECT_FILE,
) -> Requirement:
    """Return exactly one declared requirement for ``package_name``."""
    normalized_name = canonicalize_name(package_name)
    try:
        payload = tomllib.loads(project_file.read_text(encoding="utf-8"))
        raw_dependencies = payload["project"]["dependencies"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeDependencyMismatch(
            f"runtime/dependency mismatch: cannot read canonical dependency metadata from {project_file}"
        ) from exc

    matches: list[Requirement] = []
    for raw in raw_dependencies:
        requirement = Requirement(raw)
        if canonicalize_name(requirement.name) == normalized_name:
            matches.append(requirement)
    if len(matches) != 1:
        raise RuntimeDependencyMismatch(
            f"runtime/dependency mismatch: canonical metadata must declare exactly one {package_name} requirement"
        )
    return matches[0]


def validate_runtime_dependency(
    package_name: str,
    *,
    project_file: Path = PROJECT_FILE,
    version_getter: Callable[[str], str] = installed_version,
) -> tuple[str, str]:
    """Validate one installed dependency against canonical project metadata.

    Returns ``(installed_version, declared_specifier)`` on success. A missing or
    incompatible package is classified explicitly as runtime/dependency drift so
    callers do not misattribute its later import error to Agent OS product code.
    """
    requirement = declared_requirement(package_name, project_file=project_file)
    try:
        observed = version_getter(package_name)
    except PackageNotFoundError as exc:
        raise RuntimeDependencyMismatch(
            f"runtime/dependency mismatch: {package_name} is not installed; canonical requirement is {requirement.specifier}"
        ) from exc

    if observed not in requirement.specifier:
        raise RuntimeDependencyMismatch(
            f"runtime/dependency mismatch: {package_name} {observed} does not satisfy canonical requirement {requirement.specifier}"
        )
    return observed, str(requirement.specifier)
