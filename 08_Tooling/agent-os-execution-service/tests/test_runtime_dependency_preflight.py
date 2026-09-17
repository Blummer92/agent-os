from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from runtime_dependency_preflight import (
    RuntimeDependencyMismatch,
    declared_requirement,
    validate_runtime_dependency,
)


PROJECT_FILE = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_mcp_requirement_is_derived_from_canonical_package_metadata():
    requirement = declared_requirement("mcp", project_file=PROJECT_FILE)

    assert requirement.name == "mcp"
    assert "2.2.0" in requirement.specifier
    assert "2.3.0" not in requirement.specifier


def test_compatible_mcp_runtime_passes():
    observed, specifier = validate_runtime_dependency(
        "mcp",
        project_file=PROJECT_FILE,
        version_getter=lambda _: "2.2.0",
    )

    assert observed == "2.2.0"
    assert "2.2.0" in specifier


def test_incompatible_ambient_mcp_is_classified_before_product_import_failure():
    with pytest.raises(RuntimeDependencyMismatch, match="runtime/dependency mismatch"):
        validate_runtime_dependency(
            "mcp",
            project_file=PROJECT_FILE,
            version_getter=lambda _: "1.28.1",
        )


def test_missing_mcp_is_classified_as_runtime_mismatch():
    def missing(_: str) -> str:
        raise PackageNotFoundError("mcp")

    with pytest.raises(RuntimeDependencyMismatch, match="not installed"):
        validate_runtime_dependency(
            "mcp",
            project_file=PROJECT_FILE,
            version_getter=missing,
        )
