# pytest Configuration

## Version

- pytest: 7.0.0+
- pytest-cov: 4.0.0+

## pytest.ini

All Python projects must have `pytest.ini` in the root:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --strict-markers --tb=short --cov=src --cov-report=term-missing --cov-fail-under=80
markers =
    unit: marks tests as unit tests
    integration: marks tests as integration tests
    slow: marks tests as slow running
    asyncio: marks tests as async
```

## Key Options

| Option | Purpose |
|--------|---------|
| `testpaths` | Where pytest looks for tests |
| `python_files` | File naming pattern for test files |
| `python_classes` | Class naming pattern for test classes |
| `python_functions` | Function naming pattern for test functions |
| `--cov=src` | Coverage target directory |
| `--cov-fail-under=80` | Minimum coverage threshold |
| `--strict-markers` | Enforce declared markers only |

## conftest.py

Create `tests/conftest.py` with shared fixtures:

```python
"""Shared pytest configuration and fixtures."""
import pytest

@pytest.fixture
def temp_dir(tmp_path):
    """Temporary directory for test data."""
    return tmp_path
```

## Running Tests

```bash
pytest                           # Run all tests
pytest tests/unit               # Run specific directory
pytest -m unit                  # Run marked tests
pytest --cov --cov-report=html # Generate coverage report
pytest -n auto                  # Run in parallel
```
