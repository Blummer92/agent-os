# Python Testing Standard

## Overview
All Python projects must include comprehensive tests for validators, CLI, report builders, orchestration, and business logic. Tests serve as executable specifications and prevent regression of discovered issues.

## Test Framework & Tools

### Required Framework
- **Unit Testing:** pytest with pytest-cov for coverage tracking
- **Fixtures:** pytest fixtures for test data and setup/teardown
- **Mocking:** unittest.mock or pytest-mock for external dependencies
- **Integration:** pytest for integration tests with real/test databases

### Development Dependencies
```
pytest>=7.0.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-asyncio>=0.21.0
pytest-xdist>=3.0.0  # parallel execution
```

## Coverage Requirements

### Minimum Coverage Targets
- **Overall:** 80% code coverage minimum
- **Critical modules:** 90% (validators, CLI, safety-critical code)
- **Acceptable gaps:** Config files, generated code, type stubs

### Coverage Validation
- Coverage must be measured and reported in CI/CD
- Pull requests must not decrease overall coverage
- Coverage reports must include branch coverage (not just line coverage)

## Test Organization

### Directory Structure
```
project/
├── src/
│   └── module/
│       ├── __init__.py
│       ├── core.py
│       └── cli.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── unit/
│   │   ├── test_core.py
│   │   └── test_cli.py
│   ├── integration/
│   │   └── test_workflows.py
│   ├── fixtures/
│   │   ├── data.py              # Test data factories
│   │   └── mocks.py             # Common mocks
│   └── e2e/                      # End-to-end tests (optional)
│       └── test_full_flow.py
├── pytest.ini
└── pyproject.toml
```

### File Naming
- Test files: `test_*.py` or `*_test.py`
- Test functions: `test_<function>_<scenario>` (e.g., `test_validator_with_valid_input`)
- Test classes: `Test<ClassName>` (e.g., `TestValidator`)

## Unit Testing Requirements

### Test Structure
Each test should follow AAA pattern:
- **Arrange:** Set up test data and mocks
- **Act:** Call the function/method
- **Assert:** Verify results and side effects

### Test Isolation
- Each test must be independent (no shared state)
- Use fixtures for setup/teardown, not global state
- Clean up resources (files, databases) in fixtures with yield

### Naming Conventions
```python
# ✓ Good: Describes what is being tested and the scenario
def test_validator_accepts_valid_email():
def test_cli_parses_config_from_file():
def test_report_builder_handles_empty_data():

# ✗ Bad: Too vague or implementation-focused
def test_validate():
def test_parser():
def test_1():
```

### Assertion Best Practices
```python
# ✓ Good: Clear, specific, with helpful messages
assert result.status == "valid"
assert len(errors) == 0
assert "email" in result.fields

# ✗ Bad: Unclear assertions
assert result
assert error_list == []
```

## Integration Testing

### Scope
- Test interactions between components (CLI → validator → report builder)
- Test with real databases, files, or test doubles
- Test error handling and edge cases across components

### External Service Handling
- Mock external APIs and services (HTTP requests, cloud APIs)
- Use fixtures to provide test doubles
- Test retry logic and timeout behavior

### Database Testing
- Use in-memory databases (SQLite) or test containers
- Seed with minimal, reproducible data
- Clean up after each test with rollback or fixtures

### Example
```python
def test_cli_workflow_with_valid_file(tmp_path, validator):
    """Test complete CLI workflow from file input to report output."""
    # Arrange
    input_file = tmp_path / "input.csv"
    input_file.write_text("name,email\nJohn,john@example.com\n")
    
    # Act
    result = run_cli(["validate", str(input_file)])
    
    # Assert
    assert result.return_code == 0
    assert "Valid" in result.output
```

## Mocking & Fixtures

### Fixture Best Practices
```python
# conftest.py - Shared fixtures
@pytest.fixture
def sample_data():
    """Return standard test data."""
    return {"name": "test", "value": 42}

@pytest.fixture
def mock_api(mocker):
    """Mock external API calls."""
    return mocker.patch("module.external_api.fetch")

@pytest.fixture
def temp_db(tmp_path):
    """Create temporary test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()
```

### Mocking External Dependencies
```python
# ✓ Good: Mock at boundary, test logic
def test_processor_with_api_error(mocker):
    mock_api = mocker.patch("module.api.fetch")
    mock_api.side_effect = ConnectionError("API down")
    
    result = processor.process(mocker.MagicMock())
    assert result.status == "failed"

# ✗ Bad: Over-mocking, testing mock instead of logic
def test_processor(mocker):
    mocker.patch("builtins.open")
    mocker.patch("os.path")
    # Can't tell if code actually works
```

## Regression Testing

### Requirements
- Every bug fix must include a regression test
- Regression test must fail with old code, pass with fix
- Document the bug reference in test docstring

### Example
```python
def test_validator_handles_null_bytes_regression_issue_42():
    """
    Regression test for issue #42: null bytes in email field crash validator.
    
    Before fix: raises ValueError
    After fix: returns error with message
    """
    invalid_email = "test\x00@example.com"
    result = validator.validate({"email": invalid_email})
    
    assert result.status == "invalid"
    assert "null" in result.errors[0].message.lower()
```

## Async Testing

### Requirements for Async Code
```python
@pytest.mark.asyncio
async def test_async_validator():
    """Test async function."""
    result = await async_validate(test_data)
    assert result.status == "valid"

@pytest.fixture
async def async_client(mocker):
    """Fixture for async code."""
    mock = mocker.AsyncMock()
    yield mock
```

## Configuration

### pytest.ini
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    -v
    --strict-markers
    --tb=short
    --cov=src
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80
markers =
    integration: marks tests as integration tests
    slow: marks tests as slow
    e2e: marks tests as end-to-end tests
```

### pyproject.toml (Coverage)
```toml
[tool.coverage.run]
source = ["src"]
branch = true
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

## Running Tests

### Local Development
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test file
pytest tests/unit/test_core.py

# Run specific test
pytest tests/unit/test_core.py::test_validator_accepts_valid_email

# Run in parallel
pytest -n auto

# Run only fast tests (exclude slow/integration)
pytest -m "not slow and not integration"
```

### CI/CD Integration
```bash
# Full test suite with coverage report
pytest \
  --cov=src \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-fail-under=80 \
  --junitxml=test-results.xml
```

## Documentation Requirements

### Docstring Format
```python
def validator_function(data):
    """
    Validate input data against schema.
    
    Args:
        data: Dictionary to validate
        
    Returns:
        ValidationResult: Object with status and errors
        
    Raises:
        ValueError: If data is None
    """
```

### Test Docstrings
```python
def test_validator_with_empty_dict():
    """
    Test validator behavior with empty dictionary input.
    
    Expected: Returns invalid status with 'missing required fields' error
    """
```

## Continuous Integration

### Required CI Checks
- [ ] All tests pass
- [ ] Coverage ≥ 80% (≥ 90% for critical modules)
- [ ] No test regressions (fail-under enforcement)
- [ ] Flaky tests identified and fixed
- [ ] Test execution time monitored

### Failing Tests
- Must be investigated before merging
- Cannot merge with skipped/xfail tests (except approved exceptions)
- Flaky tests must be fixed or quarantined

## Best Practices Checklist

- [ ] Tests are independent (no ordering dependency)
- [ ] Tests are deterministic (no flakiness)
- [ ] Fixtures are used for setup/teardown
- [ ] External services are mocked
- [ ] Coverage targets met (80% minimum)
- [ ] Test names describe what is tested
- [ ] Tests follow AAA pattern
- [ ] No hardcoded paths or credentials
- [ ] Async tests use @pytest.mark.asyncio
- [ ] Regression tests added for bug fixes

## Anti-Patterns to Avoid

```python
# ✗ Don't: Test implementation instead of behavior
def test_loop_iterates_three_times():
    # Only cares about loop, not actual result

# ✗ Don't: Share state between tests
@pytest.fixture(scope="session")
def shared_database():  # Tests will interfere with each other

# ✗ Don't: Mock too much
def test_function(mocker):
    mocker.patch("builtins.print")
    # Can't tell if code actually works

# ✗ Don't: Use test as documentation of bug
def test_broken_bug():  # What bug? Which version?

# ✗ Don't: Hardcode test data
def test_validator():
    email = "hardcoded@example.com"  # Couples test to data
```

## Version
0.2.0

## Changelog
- 0.2.0: Complete expansion with coverage targets, fixtures, CI/CD integration
- 0.1.0: Initial testing requirement
