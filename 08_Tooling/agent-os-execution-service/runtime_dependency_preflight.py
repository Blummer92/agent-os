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


def _requirements(project_file: Path) -> tuple[Requirement, ...]:
    try:
        payload = tomllib.loads(project_file.read_text(encoding="utf-8"))
        raw_dependencies = payload["project"]["dependencies"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeDependencyMismatch(
            f"runtime/dependency mismatch: cannot read canonical dependency metadata from {project_file}"
        ) from exc

    return tuple(Requirement(raw) for raw in raw_dependencies)


def declared_requirement(
    package_name: str,
    *,
    project_file: Path = PROJECT_FILE,
) -> Requirement:
    """Return exactly one declared requirement for ``package_name``."""
    normalized_name = canonicalize_name(package_name)
    matches = [
        requirement for requirement in _requirements(project_file)
        if canonicalize_name(requirement.name) == normalized_name
    ]
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
    return _validate_installed(requirement, version_getter)


def _validate_installed(requirement: Requirement, version_getter: Callable[[str], str]) -> tuple[str, str]:
    package_name = requirement.name
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


def runtime_dependency_mismatches(
    *,
    project_file: Path = PROJECT_FILE,
    version_getter: Callable[[str], str] = installed_version,
) -> tuple[str, ...]:
    """Report every unsatisfied direct runtime dependency for this environment."""
    issues = []
    for requirement in _requirements(project_file):
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        try:
            _validate_installed(requirement, version_getter)
        except RuntimeDependencyMismatch as exc:
            issues.append(str(exc))
    return tuple(issues)
