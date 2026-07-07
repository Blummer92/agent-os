# Test Environment Setup Guide

## Overview
Consistent test environment setup ensures tests run reliably locally, in CI/CD, and across different developer machines. This guide provides templates for local development, Docker, and CI/CD pipelines.

## Local Development Setup

### 1. Create Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows
```

### 2. Install Test Dependencies
Create `requirements-dev.txt`:
```
pytest>=7.0.0
pytest-cov>=4.0.0
pytest-mock>=3.10.0
pytest-asyncio>=0.21.0
pytest-xdist>=3.0.0
coverage[toml]>=6.0.0
black>=22.0.0
flake8>=4.0.0
mypy>=0.990
```

Install:
```bash
pip install -r requirements-dev.txt
```

### 3. Configure pytest

Create `pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    -v
    --strict-markers
    --tb=short
    --cov=src
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80
markers =
    integration: marks tests as integration tests
    slow: marks tests as slow running
    asyncio: marks tests as async
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

### 4. Root Fixtures

Create `tests/conftest.py`:
```python
"""Root-level pytest configuration and fixtures."""
import os
import tempfile
from pathlib import Path
import pytest

# Ensure src is in path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

@pytest.fixture
def temp_dir():
    """Provide a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def env_var(monkeypatch):
    """Set environment variables for testing."""
    def _set_env(key, value):
        monkeypatch.setenv(key, value)
    return _set_env
```

### 5. Run Tests Locally
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific tests
pytest tests/unit/test_validators.py::TestEmailValidator::test_valid_email

# Run in parallel
pytest -n auto

# Run only fast tests
pytest -m "not slow and not integration"
```

## Docker Setup

### Development Container

Create `Dockerfile.dev`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy source code
COPY . .

# Set Python path
ENV PYTHONPATH=/app/src

CMD ["/bin/bash"]
```

### Docker Compose for Local Testing

Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.dev
    volumes:
      - .:/app
      - /app/.pytest_cache
    working_dir: /app
    environment:
      PYTHONUNBUFFERED: 1
      PYTHONDONTWRITEBYTECODE: 1
    command: pytest --cov

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: test_db
      POSTGRES_USER: test_user
      POSTGRES_PASSWORD: test_password
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test_user"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

Run with Docker Compose:
```bash
# Run tests in container
docker-compose run app

# Run specific test
docker-compose run app pytest tests/unit/test_validators.py

# Interactive shell
docker-compose run app /bin/bash
```

## CI/CD Integration

### GitHub Actions

Create `.github/workflows/tests.yml`:
```yaml
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11']

    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Lint with flake8
        run: |
          flake8 src tests --count --statistics

      - name: Type check with mypy
        run: |
          mypy src

      - name: Run tests with coverage
        env:
          DATABASE_URL: postgresql://test_user:test_password@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379
        run: |
          pytest \
            --cov=src \
            --cov-report=xml \
            --cov-report=html \
            --cov-fail-under=80 \
            --junitxml=junit.xml

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
          fail_ci_if_error: false
```

### GitLab CI

Create `.gitlab-ci.yml`:
```yaml
stages:
  - test
  - coverage

test:
  stage: test
  image: python:3.11
  services:
    - postgres:15-alpine
    - redis:7-alpine
  before_script:
    - pip install -r requirements.txt
    - pip install -r requirements-dev.txt
  script:
    - pytest --cov=src --cov-report=term-missing --cov-report=html
  coverage: '/(?i)total.*? (100(?:\.0+)?\%|[1-9]?\d(?:\.\d+)?\%)$/'
  artifacts:
    when: always
    paths:
      - htmlcov/
    reports:
      junit: junit.xml
  variables:
    POSTGRES_DB: test_db
    POSTGRES_USER: test_user
    POSTGRES_PASSWORD: test_password
```

## Environment Variables for Testing

Create `.env.test`:
```bash
# Database
TEST_DATABASE_URL=sqlite:///:memory:
# or
TEST_DATABASE_URL=postgresql://user:pass@localhost/test_db

# APIs
TEST_API_KEY=test_key_12345
TEST_API_URL=http://localhost:8000

# Redis
TEST_REDIS_URL=redis://localhost:6379/1

# Feature flags
DEBUG=true
TESTING=true
```

Load in tests:
```python
# tests/conftest.py
import os
from dotenv import load_dotenv

load_dotenv('.env.test')

@pytest.fixture(scope='session')
def test_config():
    return {
        'DATABASE_URL': os.getenv('TEST_DATABASE_URL'),
        'API_KEY': os.getenv('TEST_API_KEY'),
    }
```

## Database Setup for Tests

### SQLite In-Memory (Unit Tests)
```python
@pytest.fixture
def in_memory_db():
    """SQLite in-memory database for fast unit tests."""
    db = Database('sqlite:///:memory:')
    db.create_tables()
    yield db
    db.close()
```

### Real Database (Integration Tests)
```python
@pytest.fixture
def test_db():
    """PostgreSQL database for integration tests."""
    db_url = os.getenv('TEST_DATABASE_URL')
    db = Database(db_url)
    db.create_tables()
    db.clear_all()  # Clean slate
    
    yield db
    
    db.drop_all()
    db.close()
```

### Seeding Test Data
```python
@pytest.fixture
def populated_db(test_db):
    """Database with sample data."""
    test_db.users.insert_many([
        {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
        {'id': 2, 'name': 'Bob', 'email': 'bob@example.com'},
    ])
    
    test_db.orders.insert_many([
        {'id': 1, 'user_id': 1, 'total': 100.00},
        {'id': 2, 'user_id': 1, 'total': 200.00},
        {'id': 3, 'user_id': 2, 'total': 150.00},
    ])
    
    return test_db
```

## Mocking External Services

### Mock Server for APIs
```python
# tests/fixtures/mock_api.py
import json
from unittest.mock import Mock
import pytest

@pytest.fixture
def mock_api_responses(mocker):
    """Mock external API responses."""
    mock = mocker.patch('requests.get')
    
    # Configure responses
    mock.return_value.json.return_value = {
        'status': 'success',
        'data': {'id': 1, 'name': 'test'}
    }
    
    return mock
```

### Mock AWS Services
```python
import boto3
from moto import mock_s3, mock_dynamodb

@pytest.fixture
@mock_s3
def s3_client():
    """Mocked S3 client."""
    client = boto3.client('s3', region_name='us-east-1')
    client.create_bucket(Bucket='test-bucket')
    return client

@pytest.fixture
@mock_dynamodb
def dynamodb_table():
    """Mocked DynamoDB table."""
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName='test-table',
        KeySchema=[{'AttributeName': 'id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    return table
```

## Performance Profiling

### Profile Tests with pytest-benchmark
```bash
pip install pytest-benchmark
```

```python
def test_validator_performance(benchmark):
    """Benchmark validator performance."""
    test_data = generate_large_dataset(1000)
    
    result = benchmark(validator.validate, test_data)
    assert result.is_valid
```

Run:
```bash
pytest --benchmark-only
pytest --benchmark-min-rounds=10
```

## Debugging Tests

### Run with Debugging
```bash
# Print stdout during test execution
pytest -s

# Drop into debugger on failure
pytest --pdb

# Drop into debugger on KeyboardInterrupt
pytest --trace

# Verbose output
pytest -vv
```

### Debug Single Test
```bash
pytest tests/unit/test_validators.py::test_email_validation -vv --pdb
```

## Pre-commit Hooks

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 23.1.0
    hooks:
      - id: black

  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.0.0
    hooks:
      - id: mypy

  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest
        language: system
        pass_filenames: false
        always_run: true
        stages: [commit]
        args: ['--cov=src', '--cov-fail-under=80']
```

Install:
```bash
pip install pre-commit
pre-commit install
```

## Checklist

- [ ] Virtual environment created and activated
- [ ] Test dependencies installed (requirements-dev.txt)
- [ ] pytest.ini configured
- [ ] tests/conftest.py created with root fixtures
- [ ] CI/CD workflow configured (GitHub Actions/GitLab CI)
- [ ] Database fixtures set up for integration tests
- [ ] Environment variables configured (.env.test)
- [ ] Mock API/external service fixtures created
- [ ] Docker setup for consistent environments
- [ ] Pre-commit hooks configured
- [ ] Coverage reporting configured
- [ ] Database cleanup procedures in place

## Version
0.1.0

## Changelog
- 0.1.0: Initial test environment setup guide