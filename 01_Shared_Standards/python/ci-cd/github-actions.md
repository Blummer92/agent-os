# GitHub Actions Workflow

## Installer Policy

Use the environment-provided pip by default. Upgrade or pin pip only for a documented
compatibility requirement. Cache restoration never replaces dependency installation.

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
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
        cache: "pip"
        cache-dependency-path: requirements-dev.txt

    - name: Install dependencies
      run: python -m pip install -r requirements-dev.txt

    - name: Run tests
      run: pytest --cov=src --cov-fail-under=80

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

The `strategy.matrix` block runs each listed Python version as a separate job.

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
  run: echo "Coverage: ${{ env.COVERAGE }}"
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

Add `workflow_dispatch:` under `on:` to allow triggering from the GitHub UI. Add a
status badge to the README with `![Tests](.../workflows/tests.yml/badge.svg)`.
