"""
Pytest configuration and shared fixtures for Agent OS tests.

This module provides fixtures for testing Agent OS standards, documentation,
and governance implementations.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest


# ============================================================================
# FIXTURES: File System
# ============================================================================

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def repo_root() -> Path:
    """Path to the Agent OS repository root."""
    return Path(__file__).parent.parent


@pytest.fixture
def standards_dir(repo_root: Path) -> Path:
    """Path to the shared standards directory."""
    return repo_root / "01_Shared_Standards"


@pytest.fixture
def python_standards_dir(standards_dir: Path) -> Path:
    """Path to the Python standards directory."""
    return standards_dir / "python"


@pytest.fixture
def templates_dir(repo_root: Path) -> Path:
    """Path to the templates directory."""
    return repo_root / "03_Templates"


@pytest.fixture
def governance_dir(repo_root: Path) -> Path:
    """Path to the governance directory."""
    return repo_root / "00_Governance"


# ============================================================================
# FIXTURES: Standard Documents
# ============================================================================

@pytest.fixture
def testing_standard(python_standards_dir: Path) -> Path:
    """Path to the Python Testing Standard."""
    return python_standards_dir / "testing-standard.md"


@pytest.fixture
def unit_testing_standard(python_standards_dir: Path) -> Path:
    """Path to the Unit Testing Standard."""
    return python_standards_dir / "unit-testing-standard.md"


@pytest.fixture
def integration_testing_standard(python_standards_dir: Path) -> Path:
    """Path to the Integration Testing Standard."""
    return python_standards_dir / "integration-testing-standard.md"


@pytest.fixture
def test_environment_setup(python_standards_dir: Path) -> Path:
    """Path to the Test Environment Setup guide."""
    return python_standards_dir / "test-environment-setup.md"


# ============================================================================
# FIXTURES: Sample Test Data
# ============================================================================

@pytest.fixture
def sample_standard_file(temp_dir: Path) -> Path:
    """Create a sample standard markdown file for testing."""
    standard = temp_dir / "test-standard.md"
    standard.write_text("""# Test Standard

## Overview
This is a test standard.

## Requirements
- Requirement 1
- Requirement 2

## Version
0.1.0
""")
    return standard


@pytest.fixture
def sample_test_file(temp_dir: Path) -> Path:
    """Create a sample Python test file."""
    test_file = temp_dir / "test_example.py"
    test_file.write_text('''"""Example test file."""
import pytest


class TestExample:
    """Test example class."""

    def test_passes(self):
        """Test that passes."""
        assert True

    def test_with_parametrize(self, value):
        """Test with parameterization."""
        assert value > 0

    @pytest.mark.parametrize("value", [1, 2, 3])
    def test_multiple_values(self, value):
        """Test multiple values."""
        assert value > 0
''')
    return test_file


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (standards validation)"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )


# ============================================================================
# PYTEST HOOKS
# ============================================================================

_HOST_PRIVILEGE_TOOLCHAIN_TESTS = {
    "test_privileged_installer_refuses_to_run_unprivileged": ("sudo",),
    "test_sudo_authorizes_exactly_the_one_rendered_invocation": (
        "sudo",
        "visudo",
        "useradd",
        "userdel",
    ),
    "test_sudo_denies_every_syntactically_close_but_wrong_invocation": (
        "sudo",
        "visudo",
        "useradd",
        "userdel",
    ),
    "test_sudo_denies_every_unrelated_privileged_command": (
        "sudo",
        "visudo",
        "useradd",
        "userdel",
    ),
}


def _missing_host_privilege_tools(item) -> tuple[str, ...]:
    """Return required host-privilege executables absent from this test environment."""
    test_name = getattr(item, "originalname", None) or item.name.split("[", 1)[0]
    required = _HOST_PRIVILEGE_TOOLCHAIN_TESTS.get(test_name, ())
    return tuple(tool for tool in required if shutil.which(tool) is None)


def pytest_collection_modifyitems(config, items):
    """
    Automatically mark tests based on their path and host capabilities.

    - tests/unit/* marked as @pytest.mark.unit
    - tests/integration/* marked as @pytest.mark.integration
    - host privilege tests requiring sudo/sudoers tooling are skipped only when
      the exact external executables they exercise are unavailable
    """
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

        missing_tools = _missing_host_privilege_tools(item)
        if missing_tools:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "requires host privilege toolchain: "
                        + ", ".join(missing_tools)
                    )
                )
            )
