# Agent OS - Test Suite

This directory contains tests for Agent OS standards, governance, and implementations.

## Structure

```
tests/
├── conftest.py              # Shared pytest configuration and fixtures
├── unit/                    # Unit tests for standards validation
│   └── test_*.py           # Individual test modules
├── integration/             # Integration tests for governance workflows
│   └── test_*.py           # Individual test modules
├── fixtures/                # Shared test data and mock objects
│   ├── __init__.py
│   ├── data.py             # Sample test data
│   └── mocks.py            # Mock objects
└── README.md               # This file
```

## Running Tests

### Quick Start
```bash
# Install development dependencies
pip install -r ../requirements-dev.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run specific test file
pytest tests/unit/test_standards.py

# Run specific test
pytest tests/unit/test_standards.py::test_testing_standard_exists
```

### With Coverage
```bash
# Run tests with coverage report
pytest --cov

# Generate HTML coverage report
pytest --cov --cov-report=html
# Open htmlcov/index.html in browser

# Check coverage threshold
pytest --cov --cov-fail-under=80
```

### Advanced Options
```bash
# Show slowest tests
pytest --durations=10

# Stop on first failure
pytest -x

# Verbose with print statements
pytest -vv -s

# Run in parallel
pytest -n auto

# Drop into debugger on failure
pytest --pdb

# Run fast tests (skip slow/integration)
pytest -m "not slow and not integration"
```

## Test Standards

Agent OS tests follow the standards defined in:

- **[Python Testing Standard](../01_Shared_Standards/python/testing-standard.md)** - Framework, coverage, CI/CD
- **[Unit Testing Standard](../01_Shared_Standards/python/unit-testing-standard.md)** - Patterns, fixtures, best practices
- **[Integration Testing Standard](../01_Shared_Standards/python/integration-testing-standard.md)** - Workflows, documentation, governance

## Test Categories

### Unit Tests (tests/unit/)
- Fast (< 100ms each)
- Isolated (no dependencies)
- Test individual standards and rules
- Verify documentation completeness
- Check file formats and structure

### Integration Tests (tests/integration/)
- Test workflows across standards
- Verify governance procedures
- Check handoff processes
- Validate end-to-end scenarios
- May involve file I/O and temporary structures

## Fixtures

### Available Fixtures

```python
# Repository Paths
repo_root: Path              # Agent OS repository root
standards_dir: Path          # 01_Shared_Standards/
python_standards_dir: Path   # 01_Shared_Standards/python/
templates_dir: Path          # 03_Templates/
governance_dir: Path         # 00_Governance/

# Standard Documents
testing_standard: Path                   # testing-standard.md
unit_testing_standard: Path             # unit-testing-standard.md
integration_testing_standard: Path      # integration-testing-standard.md
test_environment_setup: Path            # test-environment-setup.md

# File System
temp_dir: Path               # Temporary directory (cleaned up after test)

# Sample Data
sample_standard_file: Path   # Sample markdown standard
sample_test_file: Path       # Sample Python test file

# Collections
markdown_files: list[Path]   # All .md files in repo
standard_files: list[Path]   # All standard files
```

### Using Fixtures in Tests

```python
import pytest

def test_standard_exists(testing_standard):
    """Test that testing standard file exists."""
    assert testing_standard.exists()
    assert testing_standard.suffix == ".md"

def test_with_temp_directory(temp_dir):
    """Test with temporary directory."""
    test_file = temp_dir / "test.md"
    test_file.write_text("# Test")
    assert test_file.exists()
    # Directory is automatically cleaned up after test

def test_all_standards_exist(standard_files):
    """Test all standards exist."""
    assert len(standard_files) > 0
    for standard in standard_files:
        assert standard.exists()
```

## Writing Tests for Standards

### Example Unit Test

```python
# tests/unit/test_testing_standard.py
import pytest


class TestTestingStandard:
    """Test the Python Testing Standard."""

    def test_standard_file_exists(self, testing_standard):
        """Test that testing standard file exists."""
        assert testing_standard.exists()

    def test_standard_has_coverage_section(self, testing_standard):
        """Test that standard defines coverage requirements."""
        content = testing_standard.read_text()
        assert "coverage" in content.lower()
        assert "80%" in content

    def test_standard_has_examples(self, testing_standard):
        """Test that standard includes code examples."""
        content = testing_standard.read_text()
        assert "```python" in content
```

### Example Integration Test

```python
# tests/integration/test_governance_workflow.py
import pytest


@pytest.mark.integration
class TestGovernanceWorkflow:
    """Test governance and standards workflows."""

    def test_standards_link_to_governance(self, python_standards_dir, governance_dir):
        """Test that standards reference governance."""
        standards = list(python_standards_dir.glob("*.md"))
        governance_files = list(governance_dir.glob("*.md"))
        
        assert len(standards) > 0
        assert len(governance_files) > 0
```

## CI/CD Integration

Tests are automatically run by GitHub Actions on:
- Push to main branch
- Pull requests
- Manual trigger

See `.github/workflows/tests.yml` for configuration.

## Common Issues

### Import Errors
```bash
# Ensure pytest finds the tests
pytest --collect-only

# Check Python path
export PYTHONPATH=.:$PYTHONPATH
```

### Fixture Not Found
```bash
# Verify conftest.py is in tests/ directory
ls -la tests/conftest.py

# Check fixture is defined
grep "def fixture_name" tests/conftest.py
```

### Tests Won't Run
```bash
# Install pytest
pip install pytest

# Install dev dependencies
pip install -r requirements-dev.txt

# Check pytest version
pytest --version  # Should be 7.0 or higher
```

## Extending the Test Suite

### Adding New Unit Tests
1. Create `tests/unit/test_<module>.py`
2. Define `Test<Module>` class
3. Use fixtures from `conftest.py`
4. Run: `pytest tests/unit/test_<module>.py`

### Adding New Integration Tests
1. Create `tests/integration/test_<workflow>.py`
2. Mark tests with `@pytest.mark.integration`
3. Use fixtures for setup/teardown
4. Run: `pytest tests/integration/test_<workflow>.py`

### Adding New Fixtures
1. Edit `tests/conftest.py`
2. Add fixture with `@pytest.fixture`
3. Document in this README
4. Use in tests

## Coverage Targets

- **Overall:** >= 80%
- **Standards validation:** >= 90%
- **Governance tests:** >= 85%

Check coverage:
```bash
pytest --cov
pytest --cov --cov-report=html  # See details in htmlcov/index.html
```

## Standards Alignment

This test suite implements:
- ✓ [Python Testing Standard v0.2.0](../01_Shared_Standards/python/testing-standard.md)
- ✓ [Unit Testing Standard v0.1.0](../01_Shared_Standards/python/unit-testing-standard.md)
- ✓ [Integration Testing Standard v0.1.0](../01_Shared_Standards/python/integration-testing-standard.md)
- ✓ [Test Environment Setup v0.1.0](../01_Shared_Standards/python/test-environment-setup.md)

## Contributing

When adding tests:
1. Follow [Unit Testing Standard](../01_Shared_Standards/python/unit-testing-standard.md)
2. Use fixtures from `conftest.py`
3. Use clear, descriptive test names: `test_<what>_<scenario>`
4. Add docstrings explaining the test
5. Ensure tests are independent
6. Run: `pytest` to verify all tests pass

## Resources

- **Testing Standards:** `01_Shared_Standards/python/`
- **Implementation Guide:** `03_Templates/prompts/implement-testing-strategy.md`
- **Templates:** `03_Templates/python-project-template/`
- **Governance:** `00_Governance/`

## Questions?

Refer to:
1. [Python Testing Standard](../01_Shared_Standards/python/testing-standard.md)
2. [Test Environment Setup](../01_Shared_Standards/python/test-environment-setup.md)
3. Run `pytest --help` for pytest options
4. See test examples in this directory
