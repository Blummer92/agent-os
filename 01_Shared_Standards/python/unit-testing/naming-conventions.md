# Test Naming Conventions

## File Names

```
test_<module>.py
```

Examples:
- `test_user_model.py` - Tests for user model
- `test_validators.py` - Tests for validators
- `test_cli.py` - Tests for CLI commands
- `test_email_service.py` - Tests for email service

## Class Names

```
Test<Feature>
```

Examples:
- `TestUserModel` - Tests for UserModel
- `TestEmailValidator` - Tests for email validation
- `TestDatabaseConnection` - Tests for DB connection

## Method Names

```
test_<what_is_being_tested>_<scenario>
```

### Structure

```
test_<function>_<condition>
```

Examples:
- `test_validate_email_with_valid_address` - Happy path
- `test_validate_email_with_invalid_format` - Error case
- `test_validate_email_raises_error` - Exception case
- `test_calculate_total_returns_sum` - Return value
- `test_create_user_saves_to_database` - Side effect

## Pattern Breakdown

### Test the Happy Path

```python
def test_validate_email_with_valid_address(self):
    """Valid email passes validation."""
    assert validate_email('test@example.com') is True
```

### Test Error Cases

```python
def test_validate_email_with_invalid_format(self):
    """Invalid email fails validation."""
    assert validate_email('not-an-email') is False
```

### Test Exceptions

```python
def test_validate_email_raises_error_on_none(self):
    """None input raises TypeError."""
    with pytest.raises(TypeError):
        validate_email(None)
```

### Test Edge Cases

```python
def test_validate_email_with_empty_string(self):
    """Empty string is invalid."""
    assert validate_email('') is False
```

## Avoid

❌ `test_1`, `test_2`, `test_foo` - Not descriptive
❌ `test_works`, `test_passes` - Too vague
❌ `testValidateEmail` - Use snake_case, not camelCase
