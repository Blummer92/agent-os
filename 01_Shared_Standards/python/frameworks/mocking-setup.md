# Mocking & External Dependencies

## Tools

- **unittest.mock** (standard library) - For simple mocking
- **pytest-mock** (3.10.0+) - Cleaner pytest integration

## When to Mock

✓ **Mock these:**
- External API calls
- Database connections
- File system operations
- Network requests
- Third-party service calls

✗ **Don't mock these:**
- Internal functions (use real code paths)
- Business logic (test actual behavior)
- Project code (test integration instead)

## Basic Patterns

### Using pytest-mock

```python
def test_api_call(mocker):
    """Mock external API."""
    mock_api = mocker.patch('module.external_api')
    mock_api.return_value = {'status': 'ok'}
    
    result = my_function()
    assert result == {'status': 'ok'}
    mock_api.assert_called_once()
```

### Using unittest.mock

```python
from unittest.mock import patch, MagicMock

def test_database():
    """Mock database connection."""
    with patch('module.db.connect') as mock_db:
        mock_db.return_value = MagicMock()
        # test code
        mock_db.assert_called()
```

## Spy vs Mock

- **Mock:** Replace with fake, return controlled value
- **Spy:** Wrap real function, track calls, let it run

```python
# Spy example
mock_api = mocker.spy(module, 'expensive_function')
result = expensive_function()
assert mock_api.call_count == 1
```
