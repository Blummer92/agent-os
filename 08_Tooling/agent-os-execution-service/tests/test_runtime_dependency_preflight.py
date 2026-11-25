from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

from runtime_dependency_preflight import (
    RuntimeDependencyMismatch,
    declared_requirement,
    validate_runtime_dependency,
)


PROJECT_FILE = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_mcp_requirement_is_derived_from_canonical_package_metadata():
    requirement = declared_requirement("mcp", project_file=PROJECT_FILE)

    assert requirement.name == "mcp"
    assert "2.3.0" in requirement.specifier
    assert "2.4.0" not in requirement.specifier


def test_compatible_mcp_runtime_passes():
    observed, specifier = validate_runtime_dependency(
        "mcp",
        project_file=PROJECT_FILE,
        version_getter=lambda _: "2.3.0",
    )

    assert observed == "2.3.0"
    assert observed in SpecifierSet(specifier)


@pytest.mark.parametrize("observed_version", ("1.28.1", "2.2.0", "2.4.0"))
def test_incompatible_ambient_mcp_is_classified_before_product_import_failure(observed_version):
    with pytest.raises(RuntimeDependencyMismatch, match="runtime/dependency mismatch"):
        validate_runtime_dependency(
            "mcp",
            project_file=PROJECT_FILE,
            version_getter=lambda _: observed_version,
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


def test_reports_all_direct_runtime_mismatches():
    from runtime_dependency_preflight import runtime_dependency_mismatches

    def installed(name):
        if name == "mcp":
            return "2.4.0"
        raise PackageNotFoundError(name)

    issues = runtime_dependency_mismatches(project_file=PROJECT_FILE, version_getter=installed)
    for package in (
        "workflow-scheduler", "agent-memory-context-manager",
        "instructional-workflow-contracts", "agent-os-navigation-registry", "mcp",
    ):
        assert any(f": {package} " in issue for issue in issues)
    assert len(issues) == 5


@pytest.mark.parametrize("runtime_installed", [False, True])
def test_bootstrap_checks_runtime_before_import_and_prioritizes_registry(tmp_path, runtime_installed):
    import os
    import shutil
    import subprocess
    import sys

    repository = tmp_path / "checkout"
    package = repository / "arbitrary" / "nesting" / "execution-service"
    suite = package / "tests"
    suite.mkdir(parents=True)
    (repository / "src/navigation_registry").mkdir(parents=True)
    (repository / "src/navigation_registry/__init__.py").write_text("OWNER = 'canonical'\n")
    (package / "navigation_registry").mkdir()
    (package / "navigation_registry/__init__.py").write_text("raise AssertionError('shadow registry')\n")
    shutil.copyfile(PROJECT_FILE.with_name("runtime_dependency_preflight.py"), package / "runtime_dependency_preflight.py")
    shutil.copyfile(Path(__file__).with_name("conftest.py"), suite / "conftest.py")
    (package / "pyproject.toml").write_text('[project]\ndependencies = ["example-one==1", "example-two==1"]\n')
    (suite / "test_integration.py").write_text(
        "from navigation_registry import OWNER\n\n"
        "def test_integration():\n    assert OWNER == 'canonical'\n"
    )
    installed = tmp_path / "distributions"
    installed.mkdir()
    if runtime_installed:
        for name in ("example-one", "example-two"):
            dist = installed / f"{name.replace('-', '_')}-1.dist-info"
            dist.mkdir()
            (dist / "METADATA").write_text(f"Name: {name}\nVersion: 1\n")

    outcome = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", str(suite)],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPATH": str(installed)},
        capture_output=True, text=True, timeout=15, check=False,
    )
    output = outcome.stdout + outcome.stderr
    if runtime_installed:
        assert outcome.returncode == 0, output
        assert "1 passed" in output
    else:
        assert outcome.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, output
        assert "1 skipped" in output
        assert "example-one is not installed" in output
        assert "example-two is not installed" in output
        assert "shadow registry" not in output
