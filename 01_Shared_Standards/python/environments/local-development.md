# Local Development Setup

## Prerequisites

- Python 3.9+ installed
- pip or conda
- Git

## Step 1: Clone Repository

```bash
git clone <repository-url>
cd <project-directory>
```

## Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

## Step 3: Install Dependencies

```bash
# Install requirements
pip install -r requirements.txt

# Install dev dependencies (testing, linting, formatting)
pip install -r requirements-dev.txt
```

## Step 4: Run Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run only unit tests
pytest tests/unit

# Run only integration tests
pytest tests/integration

# Run with coverage
pytest --cov=src --cov-report=html
```

## Step 5: Check Coverage

```bash
# Open coverage report in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## Pre-commit Hooks (Optional)

```bash
# Install pre-commit
pip install pre-commit

# Set up hooks
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

## Database Setup (if needed)

```bash
# Create test database
python -m scripts.setup_test_db

# Or with Docker Compose
docker-compose up -d db
```

## Troubleshooting

### Import Errors
```bash
# Ensure Python path is correct
export PYTHONPATH=.:$PYTHONPATH
pytest
```

### Fixture Errors
```bash
# Check conftest.py location
ls tests/conftest.py

# Verify pytest can find fixtures
pytest --fixtures | grep <fixture_name>
```

### Database Errors
```bash
# Check database connection
pytest tests/integration -v --tb=short
```
