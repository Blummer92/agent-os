# Coverage Reporting in CI/CD

## Generate Coverage in Tests

```yaml
- name: Run tests with coverage
  run: pytest --cov=src --cov-report=xml --cov-fail-under=80
```

## Upload to Codecov

```yaml
- name: Upload to Codecov
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
    flags: unittests
    name: codecov-umbrella
    fail_ci_if_error: true
```

## Coverage Badge

Add to README:

```markdown
[![codecov](https://codecov.io/gh/owner/repo/branch/main/graph/badge.svg)](https://codecov.io/gh/owner/repo)
```

Or use shields.io:

```markdown
[![Coverage](https://img.shields.io/codecov/c/github/owner/repo/main?label=coverage)](https://codecov.io/gh/owner/repo)
```

## Generate HTML Report

```bash
pytest --cov=src --cov-report=html
```

View results:

```bash
open htmlcov/index.html
```

## Multiple Formats

Generate several report formats:

```yaml
- name: Generate coverage reports
  run: |
    pytest \
      --cov=src \
      --cov-report=xml \
      --cov-report=html \
      --cov-report=term-missing \
      --cov-fail-under=80
```

## Fail on Coverage Drop

Prevent merging if coverage decreases:

```yaml
- name: Check coverage threshold
  run: pytest --cov=src --cov-fail-under=80
```

This blocks PR if:
- Overall coverage < 80%
- Coverage decreased from previous commit

## Report Artifacts

Save coverage HTML as artifact:

```yaml
- name: Upload coverage report
  uses: actions/upload-artifact@v3
  with:
    name: coverage-report
    path: htmlcov/
```

Then download and view locally.

## Coverage Trends

Track coverage over time with Codecov:

1. Push coverage to Codecov
2. Codecov tracks historical data
3. See trends in dashboard
4. Alerts on significant drops

Result: Coverage trends visible in PR checks.
