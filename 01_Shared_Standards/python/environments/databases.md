# Database Configuration

## Choose Your Database

**For tests:** Use [sqlite-testing.md](sqlite-testing.md) (recommended, fastest)

**For real database:** Use PostgreSQL below

## PostgreSQL Setup

### Local Installation

```bash
# macOS
brew install postgresql
brew services start postgresql
createdb testdb

# Ubuntu
sudo apt-get install postgresql
sudo service postgresql start
createdb testdb
```

### Docker Setup

```bash
docker run --name testdb \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=testdb \
  -p 5432:5432 \
  -d postgres:15-alpine
```

Connection string:
```
postgresql://postgres:testpass@localhost:5432/testdb
```

## Configuration

```python
# conftest.py
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv('.env.test')
DATABASE_URL = os.getenv('DATABASE_URL')

@pytest.fixture
def test_db():
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
```

## Cleanup Options

```python
# Option 1: Fresh per test
@pytest.fixture
def test_db():
    # Creates fresh database each test

# Option 2: Rollback after test
@pytest.fixture
def test_db():
    session.begin()
    yield session
    session.rollback()

# Option 3: Truncate tables
@pytest.fixture
def test_db():
    yield session
    for table in Base.metadata.tables.values():
        session.execute(table.delete())
    session.commit()
```
