"""
Pytest configuration and shared fixtures for Agent OS tests.

This module provides fixtures for testing Agent OS standards, documentation,
and governance implementations.
"""
import os
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
# FIXTURES: Validation
# ============================================================================

@pytest.fixture
def markdown_files(repo_root: Path) -> list[Path]:
    """Get all markdown files in the repository."""
    return list(repo_root.rglob("*.md"))


@pytest.fixture
def standard_files(python_standards_dir: Path) -> list[Path]:
    """Get all standard markdown files."""
    return list(python_standards_dir.glob("*.md"))


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

def pytest_collection_modifyitems(config, items):
    """
    Automatically mark tests based on their path.

    - tests/unit/* marked as @pytest.mark.unit
    - tests/integration/* marked as @pytest.mark.integration
    """
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
