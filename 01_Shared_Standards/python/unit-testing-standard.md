# Python Unit Testing Standard

## Overview
Unit tests verify individual functions, methods, and classes in isolation. They form the foundation of test coverage and should be written alongside or before implementation (TDD-optional, but encouraged).

## Scope
- Single function or method behavior
- Edge cases and error conditions
- Input validation
- Return values and side effects
- Exception handling

## Test Size Characteristics
- **Execution:** < 100ms per test (fail-fast principle)
- **Setup:** Minimal, using fixtures
- **Assertions:** 1-5 assertions per test (focus on one behavior)
- **Dependencies:** All external calls mocked

## Structure Template

```python
class TestValidatorFunction:
    """Tests for validator_function."""
    
    def test_valid_input_returns_success(self):
        """Test validator accepts valid input."""
        result = validator_function({"email": "test@example.com"})
        assert result.is_valid
        assert result.errors == []
    
    def test_invalid_email_returns_error(self):
        """Test validator rejects invalid email."""
        result = validator_function({"email": "not-an-email"})
        assert not result.is_valid
        assert "email" in result.errors
    
    def test_missing_required_field_returns_error(self):
        """Test validator rejects missing required fields."""
        result = validator_function({})
        assert not result.is_valid
        assert any("required" in err for err in result.errors)
    
    def test_raises_on_none_input(self):
        """Test validator raises ValueError for None input."""
        with pytest.raises(ValueError, match="input required"):
            validator_function(None)
```

## Test Categories

### Happy Path Tests
- Test with valid, typical input
- Verify expected success behavior
- Check return values are correct

### Edge Case Tests
- Empty inputs ([], {}, "", None)
- Boundary values (0, max int, min int)
- Special characters and unicode
- Very large inputs

### Error Handling Tests
- Invalid input format
- Missing required fields
- Out-of-range values
- Type mismatches
- Exception handling

### State & Side Effect Tests
- Objects modified as expected
- Database records created/updated
- Files written correctly
- Logs recorded

## Parameterized Tests

Use `@pytest.mark.parametrize` to test multiple scenarios:

```python
@pytest.mark.parametrize("email,expected", [
    ("valid@example.com", True),
    ("invalid-email", False),
    ("", False),
    ("test@example.co.uk", True),
])
def test_email_validation(email, expected):
    """Test email validation with multiple inputs."""
    result = validator_function({"email": email})
    assert result.is_valid == expected
```

## Naming Patterns

### Function Under Test (SUT) in Name
```python
# Clear what's being tested
def test_csv_parser_handles_quoted_fields():
def test_email_validator_rejects_empty_string():
def test_report_builder_sorts_by_name():

# Unclear
def test_parser():
def test_handles_quotes():
```

### Scenario in Name
```python
# Describes the condition
def test_with_valid_input():
def test_with_empty_list():
def test_raises_on_none():

# Too vague
def test_basic():
def test_working():
```

## Fixture Usage

### Local Fixtures (per test file)
```python
# conftest.py in tests/unit/
@pytest.fixture
def sample_user_data():
    return {
        "name": "John Doe",
        "email": "john@example.com",
        "age": 30,
    }

@pytest.fixture
def validator():
    """Return a configured validator instance."""
    return UserValidator(strict_mode=True)
```

### Shared Fixtures (across project)
```python
# tests/conftest.py - Root level fixtures
@pytest.fixture
def temp_file(tmp_path):
    """Provide a temporary file path."""
    return tmp_path / "test.txt"
```

## Mocking Patterns

### Mock External API Calls
```python
def test_processor_fetches_data(mocker):
    """Test processor calls external API."""
    mock_api = mocker.patch("module.api.fetch_user")
    mock_api.return_value = {"id": 1, "name": "John"}
    
    result = processor.get_user(1)
    
    assert result["name"] == "John"
    mock_api.assert_called_once_with(1)
```

### Mock File Operations
```python
def test_report_writes_file(mocker, tmp_path):
    """Test report generation writes correct file."""
    output_file = tmp_path / "report.txt"
    
    report_builder.generate(output_file)
    
    assert output_file.exists()
    assert "Summary" in output_file.read_text()
```

### Mock System Commands
```python
def test_cli_runs_subprocess(mocker):
    """Test CLI executes system command."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    
    result = cli.execute_command("python script.py")
    
    mock_run.assert_called_once()
    assert result is True
```

## Assertion Patterns

### Equality Assertions
```python
# Direct equality
assert result == expected
assert status_code == 200

# Membership
assert "error" in result.messages
assert email in user.emails
assert 5 in range(1, 10)
```

### Type Assertions
```python
assert isinstance(result, ValidationResult)
assert type(data) == dict
```

### Comparison Assertions
```python
assert count > 0
assert price <= budget
assert len(items) == 3
```

### Exception Assertions
```python
# Verify exception is raised
with pytest.raises(ValueError):
    invalid_function()

# Verify exception message
with pytest.raises(ValueError, match="email required"):
    validator_function({})

# Verify exception type and message
with pytest.raises(ConnectionError) as exc_info:
    api.fetch()
assert "timeout" in str(exc_info.value)
```

### No-op Assertions (use sparingly)
```python
# Verify function doesn't raise
result = risky_function()
# If we get here, no exception was raised

# Verify mock was called
mock_function.assert_called_once()
mock_function.assert_called_with(1, 2)
```

## Coverage Requirements by Module Type

### Data Models & Classes: 90%+ coverage
```python
class User:
    """Critical domain model - should be fully tested."""
    def __init__(self, name, email):
        self.name = name
        self.email = email
    
    def validate(self):
        """Every method should be tested."""
        return self.email and self.name
```

### Validators & Rules: 90%+ coverage
```python
def validate_email(email):
    """Security-critical - high coverage required."""
    # All branches should be tested
```

### Utilities & Helpers: 80%+ coverage
```python
def format_date(date_obj):
    """General utility - standard coverage."""
    # Most paths should be tested
```

### Config & Setup: 50%+ coverage
```python
# Configuration loading - lower coverage acceptable
CONFIG = load_config()
```

## Anti-Patterns to Avoid

```python
# ✗ DON'T: Test too many things at once
def test_user_workflow():
    # Tests validate, save, fetch, delete - should be separate tests

# ✗ DON'T: Make tests dependent on each other
def test_1_setup():
    # Sets up data
def test_2_uses_data():
    # Depends on test_1 running first

# ✗ DON'T: Use sleep() for timing
def test_async_operation():
    sleep(1)
    assert result  # Slow and unreliable

# ✗ DON'T: Leave test data in shared state
def test_function():
    global test_data  # ✗ Bad
    test_data = setup()

# ✗ DON'T: Test random behavior without seeding
def test_shuffle():
    random.shuffle(items)  # Non-deterministic

# ✗ DON'T: Hardcode test data across multiple files
# tests/test_a.py
test_email = "john@example.com"
# tests/test_b.py
test_email = "john@example.com"  # Duplicated
```

## Performance Considerations

### Test Speed Goals
- Unit tests: < 10ms each (< 1 second for full suite)
- Don't hit databases, APIs, or file system
- Use in-memory data structures
- Mock slow operations

### Slow Test Markers
```python
@pytest.mark.slow
def test_complex_calculation():
    """Runs slow calculation - skipped by default."""
    pass

# Run only fast tests
pytest -m "not slow"
```

## Version
0.1.0

## Changelog
- 0.1.0: Initial unit testing standard