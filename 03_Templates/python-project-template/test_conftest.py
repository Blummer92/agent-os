"""
Root-level pytest configuration and shared fixtures.

Place this file as: tests/conftest.py
"""
import os
import sys
import tempfile
from pathlib import Path
from typing import Generator, Any

import pytest

# Add src directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================================
# FIXTURES: File System
# ============================================================================

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory that's cleaned up after the test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_file(temp_dir: Path) -> Path:
    """Provide a path to a temporary file."""
    return temp_dir / "test_file.txt"


@pytest.fixture
def sample_csv_file(temp_dir: Path) -> Path:
    """Provide a sample CSV file for testing."""
    csv_path = temp_dir / "sample.csv"
    csv_path.write_text("id,name,email\n1,John,john@example.com\n2,Jane,jane@example.com\n")
    return csv_path


# ============================================================================
# FIXTURES: Database
# ============================================================================

@pytest.fixture
def test_db_connection():
    """
    Provide a test database connection.

    Override this fixture in conftest.py with your actual database implementation.
    Example:
        @pytest.fixture
        def test_db_connection():
            db = Database('sqlite:///:memory:')
            db.create_tables()
            yield db
            db.close()
    """
    # Example implementation - override with your database
    class MockDB:
        def __init__(self):
            self.data = {}

        def insert(self, table: str, record: dict) -> int:
            if table not in self.data:
                self.data[table] = {}
            max_id = max(self.data[table].keys()) if self.data[table] else 0
            new_id = max_id + 1
            record['id'] = new_id
            self.data[table][new_id] = record
            return new_id

        def get(self, table: str, id: int) -> dict:
            return self.data[table].get(id)

        def close(self):
            self.data.clear()

    db = MockDB()
    yield db
    db.close()


# ============================================================================
# FIXTURES: Environment Variables
# ============================================================================

@pytest.fixture
def env_var(monkeypatch):
    """
    Fixture for setting environment variables during tests.

    Usage:
        def test_something(env_var):
            env_var('MY_VAR', 'test_value')
            # MY_VAR is now set to 'test_value'
    """
    def _set_var(key: str, value: str) -> None:
        monkeypatch.setenv(key, value)

    return _set_var


@pytest.fixture
def clean_env(monkeypatch):
    """Clear all environment variables for a clean test environment."""
    monkeypatch.delenv('API_KEY', raising=False)
    monkeypatch.delenv('DEBUG', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)


# ============================================================================
# FIXTURES: Sample Data
# ============================================================================

@pytest.fixture
def sample_user_data() -> dict:
    """Return sample user data for testing."""
    return {
        "id": 1,
        "name": "John Doe",
        "email": "john@example.com",
        "age": 30,
    }


@pytest.fixture
def sample_users_list() -> list[dict]:
    """Return a list of sample users."""
    return [
        {"id": 1, "name": "Alice", "email": "alice@example.com"},
        {"id": 2, "name": "Bob", "email": "bob@example.com"},
        {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
    ]


@pytest.fixture
def sample_validation_data() -> dict:
    """Return sample data for validation tests."""
    return {
        "name": "John",
        "email": "john@example.com",
        "phone": "555-1234",
    }


# ============================================================================
# FIXTURES: Mocking
# ============================================================================

@pytest.fixture
def mock_config(monkeypatch):
    """
    Fixture for mocking configuration.

    Usage:
        def test_something(mock_config):
            mock_config('API_URL', 'http://localhost:8000')
    """
    def _set_config(key: str, value: Any) -> None:
        monkeypatch.setenv(key, str(value))

    return _set_config


@pytest.fixture
def mock_external_api(mocker):
    """
    Fixture for mocking external API calls.

    Usage:
        def test_something(mock_external_api):
            mock = mock_external_api('requests.get', return_value={'status': 'ok'})
    """
    def _mock_api(target: str, **kwargs) -> Any:
        return mocker.patch(target, **kwargs)

    return _mock_api


# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
    config.addinivalue_line(
        "markers", "asyncio: marks tests as async"
    )


# ============================================================================
# PYTEST HOOKS
# ============================================================================

def pytest_collection_modifyitems(config, items):
    """
    Automatically mark tests based on their path.

    - tests/integration/* marked as @pytest.mark.integration
    - tests/slow/* marked as @pytest.mark.slow
    """
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        if "slow" in str(item.fspath):
            item.add_marker(pytest.mark.slow)
