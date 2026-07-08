# Database Testing Setup

## In-Memory SQLite (Recommended)

Fastest for tests, no setup required:

```python
# conftest.py
import pytest
from sqlalchemy import create_engine

@pytest.fixture
def test_db():
    """In-memory database."""
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    session.close()
```

## PostgreSQL (Local)

For integration tests needing real database:

```bash
# Install PostgreSQL
brew install postgresql  # macOS
sudo apt-get install postgresql  # Ubuntu

# Start server
brew services start postgresql  # macOS

# Create test database
createdb testdb
```

Configuration:

```python
# conftest.py
import pytest
from sqlalchemy import create_engine

@pytest.fixture
def test_db():
    """PostgreSQL test database."""
    engine = create_engine(
        'postgresql://postgres:password@localhost/testdb'
    )
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(engine)  # Clean up
```

## PostgreSQL (Docker)

```bash
# Start PostgreSQL container
docker run --name testdb \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=testdb \
  -p 5432:5432 \
  -d postgres:15-alpine

# Connection string
postgresql://postgres:testpass@localhost:5432/testdb

# Stop container
docker stop testdb
docker rm testdb
```

## Environment Variables

Create `.env.test`:

```env
DATABASE_URL=postgresql://postgres:testpass@localhost/testdb
```

Load in tests:

```python
import os
from dotenv import load_dotenv

load_dotenv('.env.test')
DATABASE_URL = os.getenv('DATABASE_URL')
```

## Database Migrations

For projects with Alembic:

```python
@pytest.fixture(scope='session')
def db_migrations():
    """Run migrations once per session."""
    from alembic.config import Config
    from alembic import command
    
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    return True

@pytest.fixture
def test_db(db_migrations):
    """Test database after migrations."""
    # ...
```

## Cleanup Strategies

### Option 1: Recreate Each Test
```python
@pytest.fixture
def test_db():
    # Fresh database per test
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    # ...
```

### Option 2: Rollback Transactions
```python
@pytest.fixture
def test_db():
    # Rollback changes after test
    session.begin()
    yield session
    session.rollback()
```

### Option 3: Truncate Tables
```python
@pytest.fixture
def test_db():
    yield session
    # Clear data
    for table in Base.metadata.tables.values():
        session.execute(table.delete())
    session.commit()
```
