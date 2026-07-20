# CI/CD Setup (GitHub Actions)

Use the installer policy in `../ci-cd/github-actions.md`: keep the environment-provided
pip unless a documented compatibility requirement justifies a constrained version.

## Workflow File

Create `.github/workflows/tests.yml`:

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']

    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: "pip"
        cache-dependency-path: requirements-dev.txt

    - name: Install dependencies
      run: python -m pip install -r requirements-dev.txt

    - name: Run tests
      run: pytest --cov=src --cov-report=xml

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      with:
        file: ./coverage.xml

    - name: Code quality checks
      run: |
        flake8 src tests
        black --check src tests
        mypy src
```

## Branch Protection Rules

In GitHub repository settings:

1. Go to **Settings** → **Branches**.
2. Add a rule for `main`.
3. Require pull-request reviews, passing status checks, and current branches.

Documentation does not authorize a repository-setting change. Follow the repository's
protected-branch governance and approved settings-change process.

## Check Status in PR

Workflow results show in the pull request:

- ✓ All tests passed
- ✗ Tests failed; open the check for logs

## Local vs CI

Run locally before pushing:

```bash
pytest --cov=src --cov-fail-under=80
flake8 src tests
black src tests
mypy src
```

This matches the example CI checks.
