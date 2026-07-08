# Integration Testing Standards

## Quick Links

- **[workflow-testing.md](workflow-testing.md)** - Test complete workflows
- **[database-testing.md](database-testing.md)** - Database integration
- **[api-testing.md](api-testing.md)** - API endpoint testing
- **[cli-testing.md](cli-testing.md)** - CLI command testing
- **[error-testing.md](error-testing.md)** - Error scenarios

## What Are Integration Tests?

Integration tests verify multiple components working together:

- **Slower:** < 1 second per test
- **Real dependencies:** Database, file system, APIs
- **Complete workflows:** End-to-end scenarios
- **Error scenarios:** Handle failures correctly

## File Organization

```
tests/integration/
├── test_user_workflow.py
├── test_api_endpoints.py
├── test_database_operations.py
└── test_cli_commands.py
```

## Mark as Integration

```python
import pytest

@pytest.mark.integration
def test_complete_workflow():
    """Test complete workflow."""
    # ...
```

## Running Integration Tests

```bash
pytest tests/integration                # All integration tests
pytest tests/integration -v            # Verbose output
pytest -m integration                  # By marker
pytest --co -m integration             # Show which tests
```

## vs Unit Tests

| Aspect | Unit | Integration |
|--------|------|-------------|
| Speed | < 100ms | < 1s |
| Dependencies | Mocked | Real |
| Scope | Single function | Multiple components |
| Database | Mocked | Real or test DB |
| Files | Mocked | Real temp files |
