# GitHub Actions Workflow

## Basic Workflow

Create `.github/workflows/tests.yml`:

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        pip install --upgrade pip
        pip install -r requirements-dev.txt

    - name: Run tests
      run: pytest --cov=src --cov-fail-under=80

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## Testing Multiple Python Versions

The `matrix` strategy runs tests on multiple versions:

```yaml
strategy:
  matrix:
    python-version: ['3.9', '3.10', '3.11', '3.12']
```

Each combination creates separate job.

## Service Dependencies

For database/Redis in tests:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    env:
      POSTGRES_PASSWORD: testpass
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
    ports:
      - 5432:5432
```

## Conditional Steps

Only run on main branch:

```yaml
- name: Report coverage
  if: github.ref == 'refs/heads/main'
  run: |
    echo "Coverage: ${{ env.COVERAGE }}"
```

## Artifact Upload

Save test results:

```yaml
- name: Upload test results
  if: always()
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: test-results.xml
```

## Manual Trigger

Allow manual workflow run:

```yaml
on:
  workflow_dispatch:
```

Then use GitHub UI to trigger manually.

## Status Badge

Add to README:

```markdown
![Tests](https://github.com/owner/repo/actions/workflows/tests.yml/badge.svg)
```
