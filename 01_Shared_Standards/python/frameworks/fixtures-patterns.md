# pytest Fixtures

## What Are Fixtures?

Fixtures provide test data, setup, and teardown. They're reusable across tests.

## Fixture Scope

```python
@pytest.fixture(scope='function')  # Default: runs per test
def per_test():
    return 'value'

@pytest.fixture(scope='module')    # Runs once per module
def per_module():
    return 'value'

@pytest.fixture(scope='session')   # Runs once per session
def per_session():
    return 'value'
```

## Basic Pattern

```python
# tests/conftest.py
import pytest

@pytest.fixture
def sample_data():
    """Provide test data."""
    return {'id': 1, 'name': 'Test'}

@pytest.fixture
def temp_file(tmp_path):
    """Create temporary file."""
    file = tmp_path / 'test.txt'
    file.write_text('content')
    return file

# Usage in tests
def test_with_fixture(sample_data):
    assert sample_data['id'] == 1

def test_multiple_fixtures(sample_data, temp_file):
    assert sample_data is not None
    assert temp_file.exists()
```

## Cleanup with yield

```python
@pytest.fixture
def database():
    """Connect and cleanup."""
    db = Database()
    db.connect()
    yield db  # Test runs here
    db.close()  # Cleanup after
```

## Fixture Dependencies

```python
@pytest.fixture
def user(sample_data):
    """Fixtures can depend on other fixtures."""
    return User(**sample_data)

@pytest.fixture
def logged_in_user(user):
    """Stack dependencies."""
    user.login()
    return user
```
