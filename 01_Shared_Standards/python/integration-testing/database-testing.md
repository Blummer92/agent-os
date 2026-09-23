# Database Integration Testing

## Test Database Setup

### In-Memory SQLite (Recommended for Tests)

```python
# conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def test_db():
    """Create in-memory database for testing."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()
```

## Test Database Operations

```python
@pytest.mark.integration
class TestDatabaseOperations:
    """Test database CRUD operations."""
    
    def test_create_and_retrieve_user(self, test_db):
        """Test creating and retrieving from database."""
        # CREATE
        user = User(name='John', email='john@example.com')
        test_db.add(user)
        test_db.commit()
        
        # RETRIEVE
        found = test_db.query(User).filter_by(email='john@example.com').first()
        assert found.name == 'John'
        assert found.id is not None
```

## Test Relationships

```python
def test_user_orders_relationship(self, test_db):
    """Test user-to-orders relationship."""
    user = User(name='Jane')
    order1 = Order(user=user, total=100)
    order2 = Order(user=user, total=200)
    
    test_db.add_all([user, order1, order2])
    test_db.commit()
    
    # Verify relationship
    found_user = test_db.query(User).first()
    assert len(found_user.orders) == 2
```

## Test Transactions

```python
def test_transaction_rollback(self, test_db):
    """Test transaction rollback on error."""
    user = User(name='Test')
    test_db.add(user)
    test_db.commit()
    initial_id = user.id
    
    # Cause error during transaction
    try:
        user.name = None  # Invalid
        test_db.commit()
    except Exception:
        test_db.rollback()
    
    # Verify rollback
    found = test_db.query(User).filter_by(id=initial_id).first()
    assert found.name != None
```

## Fixtures for Clean State

```python
@pytest.fixture
def populated_db(test_db):
    """Database pre-populated with test data."""
    users = [
        User(name='Alice', email='alice@example.com'),
        User(name='Bob', email='bob@example.com'),
    ]
    test_db.add_all(users)
    test_db.commit()
    return test_db
```
