# SQLite Testing Setup

## In-Memory Database (Recommended)

Fastest for tests, no setup required:

```python
# conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def test_db():
    """In-memory SQLite database."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    session.close()
```

## Usage in Tests

```python
@pytest.mark.integration
def test_create_user(test_db):
    """Test database create operation."""
    user = User(name='John', email='john@example.com')
    test_db.add(user)
    test_db.commit()
    
    found = test_db.query(User).filter_by(email='john@example.com').first()
    assert found.name == 'John'
```

## Advantages

- ✓ No setup required
- ✓ Very fast (in-memory)
- ✓ Complete isolation per test
- ✓ Perfect for unit/integration tests
- ✓ Works in CI/CD without services

## When to Use

Use SQLite for:
- Unit tests with database
- Integration tests
- CI/CD pipelines
- Local development

Use PostgreSQL for:
- Production testing
- Complex queries
- Performance testing
- Real database features
