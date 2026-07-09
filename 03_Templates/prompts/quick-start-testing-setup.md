# Quick-Start: Setting Up Testing Standards in Your Python Project

A practical, step-by-step guide to implement Agent OS testing standards in any Python project.

## Prerequisites

- Python 3.9 or higher
- pip or uv for package management
- Git repository initialized
- 30-45 minutes for complete setup

## Phase 1: Project Structure (5 minutes)

### 1.1 Create test directories

```bash
# From your project root
mkdir -p tests/unit
mkdir -p tests/integration
mkdir -p tests/fixtures
```

### 1.2 Create placeholder files

```bash
# Makes directories git-trackable
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py
touch tests/fixtures/__init__.py
touch tests/fixtures/__init__.py
```

### 1.3 Verify structure

Your project should now look like:

```
my-project/
├── src/
│   └── my_module/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py          (you'll create this in Phase 2)
│   ├── unit/
│   │   ├── __init__.py
│   │   └── test_*.py
│   ├── integration/
│   │   ├── __init__.py
│   │   └── test_*.py
│   └── fixtures/
│       ├── __init__.py
│       └── *.json, *.yaml, etc.
└── pytest.ini               (you'll create this in Phase 2)
```

## Phase 2: Configure pytest (10 minutes)

### 2.1 Install test dependencies

```bash
pip install pytest>=7.0 pytest-cov pytest-mock pytest-asyncio pytest-xdist
```

### 2.2 Create pytest.ini

Save as `pytest.ini` in your project root:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

# Output options
addopts = 
    -v
    --strict-markers
    --tb=short
    --cov=src
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80

# Custom markers
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (slower, with dependencies)
    slow: Tests that take > 1 second
    asyncio: Async/await tests
```

### 2.3 Create conftest.py

Save as `tests/conftest.py`:

```python
"""Shared pytest configuration and fixtures."""
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root():
    """Return repository root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_data():
    """Provide sample data for tests."""
    return {
        "name": "Test User",
        "email": "test@example.com",
        "age": 30,
    }


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables for tests."""
    test_env = {
        "APP_ENV": "test",
        "DEBUG": "false",
    }
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    return test_env
```

## Phase 3: Write Your First Tests (15 minutes)

### 3.1 Create a unit test

Save as `tests/unit/test_example.py`:

```python
"""Example unit tests following AAA pattern."""
import pytest


class TestExample:
    """Test basic functionality."""

    def test_addition(self):
        """Test that addition works correctly."""
        # ARRANGE
        a = 5
        b = 3
        
        # ACT
        result = a + b
        
        # ASSERT
        assert result == 8

    def test_string_validation(self):
        """Test string validation."""
        # ARRANGE
        test_string = "hello"
        
        # ACT & ASSERT
        assert isinstance(test_string, str)
        assert len(test_string) == 5
        assert test_string.startswith("h")

    @pytest.mark.parametrize("input_value,expected", [
        (1, 2),
        (2, 3),
        (0, 1),
        (-1, 0),
    ])
    def test_increment(self, input_value, expected):
        """Test increment with multiple values."""
        result = input_value + 1
        assert result == expected
```

### 3.2 Create an integration test

Save as `tests/integration/test_workflow.py`:

```python
"""Example integration tests."""
import pytest


@pytest.mark.integration
class TestWorkflow:
    """Test complete workflows."""

    def test_user_creation_workflow(self, sample_data):
        """Test complete user creation process."""
        # ARRANGE
        data = sample_data
        
        # ACT
        user = {
            "id": 1,
            "name": data["name"],
            "email": data["email"],
        }
        
        # ASSERT
        assert user["id"] == 1
        assert user["name"] == "Test User"
        assert "@" in user["email"]

    def test_error_handling(self):
        """Test error handling in workflow."""
        # ARRANGE
        invalid_email = "not-an-email"
        
        # ACT & ASSERT
        with pytest.raises(ValueError):
            if "@" not in invalid_email:
                raise ValueError("Invalid email format")
```

## Phase 4: Run Tests (5 minutes)

### 4.1 Run all tests

```bash
# Run all tests with coverage
pytest

# Expected output:
# ============ test session starts ============
# collected 6 items
#
# tests/unit/test_example.py::TestExample::test_addition PASSED
# tests/unit/test_example.py::TestExample::test_string_validation PASSED
# tests/unit/test_example.py::TestExample::test_increment[1-2] PASSED
# ...
# ============ 6 passed in 0.15s ============
```

### 4.2 View coverage report

```bash
# Terminal coverage report
pytest --cov=src --cov-report=term-missing

# HTML coverage report
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

### 4.3 Run specific test categories

```bash
# Only unit tests
pytest tests/unit/

# Only integration tests
pytest tests/integration/

# Only fast tests
pytest -m "not slow"
```

## Phase 5: Set Up CI/CD (10 minutes)

### 5.1 Create GitHub Actions workflow

Save as `.github/workflows/tests.yml`:

```yaml
name: Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11", "3.12"]

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install pytest pytest-cov pytest-mock pytest-asyncio
        pip install -e .
    
    - name: Run tests
      run: pytest --cov=src --cov-report=xml
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        files: ./coverage.xml
        fail_ci_if_error: false
```

### 5.2 Create .github/workflows/ directory if needed

```bash
mkdir -p .github/workflows
# Paste workflow file from 5.1 above
```

## Phase 6: Best Practices Checklist

- [ ] All tests follow AAA (Arrange-Act-Assert) pattern
- [ ] Test names clearly describe what's being tested: `test_<function>_<scenario>`
- [ ] Tests are isolated and don't depend on each other
- [ ] Unit tests run in < 100ms each
- [ ] Integration tests marked with `@pytest.mark.integration`
- [ ] Coverage is at least 80% overall
- [ ] Critical modules have 90%+ coverage
- [ ] conftest.py contains shared fixtures
- [ ] pytest.ini exists and is configured
- [ ] CI/CD runs tests on multiple Python versions
- [ ] Coverage reports are tracked over time

## Phase 7: Next Steps

### For more detailed information, consult these standards:

- **Patterns**: `01_Shared_Standards/python/unit-testing/patterns.md`
  - Deep dive into AAA pattern with real examples
  
- **Naming**: `01_Shared_Standards/python/unit-testing/naming-conventions.md`
  - Guidelines for clear, descriptive test names

- **Assertions**: `01_Shared_Standards/python/unit-testing/assertions.md`
  - Best practices for assertions and error testing

- **Fixtures**: `01_Shared_Standards/python/frameworks/fixtures-patterns.md`
  - Advanced fixture patterns and scope handling

- **Coverage**: `01_Shared_Standards/python/coverage/measurement.md`
  - How to measure and improve code coverage

- **CI/CD**: `01_Shared_Standards/python/ci-cd/github-actions.md`
  - Complete GitHub Actions configuration guide

- **Environments**: `01_Shared_Standards/python/environments/local-development.md`
  - Complete local development environment setup

### Common Tasks

**Add a new test file:**
```bash
# Create test file
touch tests/unit/test_my_feature.py

# Add test class following AAA pattern
# See: 01_Shared_Standards/python/unit-testing/patterns.md
```

**Increase test coverage:**
```bash
# Identify uncovered lines
pytest --cov=src --cov-report=term-missing

# Focus on high-value code first
# See: 01_Shared_Standards/python/coverage/requirements.md
```

**Debug failing test:**
```bash
# Verbose output
pytest tests/unit/test_example.py::TestExample::test_addition -vv

# Show print statements
pytest tests/unit/test_example.py -s

# Drop into debugger on failure
pytest tests/unit/test_example.py --pdb
```

**Run tests in parallel:**
```bash
pip install pytest-xdist
pytest -n auto
```

## Troubleshooting

### "ModuleNotFoundError: No module named 'src'"

Install your package in development mode:
```bash
pip install -e .
```

Make sure `pyproject.toml` or `setup.py` exists and is properly configured.

### "Coverage is below 80%"

This is expected for new projects. Focus on the most critical code first:
- Data models (90% coverage)
- Business logic (85% coverage)
- Utilities (75% coverage)

See: `01_Shared_Standards/python/coverage/requirements.md`

### "Pytest can't find my tests"

Verify your directory structure:
```bash
# Check that pytest.ini testpaths is correct
cat pytest.ini | grep testpaths

# Verify tests/ directory exists
ls -la tests/
```

### "Tests pass locally but fail in CI"

Check Python version differences:
```bash
# Test with multiple versions locally
pytest tests/
python3.10 -m pytest tests/
python3.11 -m pytest tests/
```

## Summary

You now have:

✅ Test directory structure  
✅ pytest configured with coverage tracking  
✅ Example unit and integration tests  
✅ GitHub Actions CI/CD pipeline  
✅ 80%+ code coverage baseline  
✅ Best practices documentation to reference  

**Total setup time:** 30-45 minutes  
**Tests created:** 6 examples (unit + integration)  
**Coverage baseline:** Ready for 80% minimum

Next: Add tests for your actual code, gradually reaching 80%+ coverage. Refer to the standards documents in `01_Shared_Standards/python/` for detailed guidance on specific scenarios.
