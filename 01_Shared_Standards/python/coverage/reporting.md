# Coverage Reporting

## HTML Report

Generate detailed HTML report:

```bash
pytest --cov=src --cov-report=html
# Open: htmlcov/index.html
```

### Reading the Report

1. **Red lines:** Not executed
2. **Yellow lines:** Partially executed (branch not covered)
3. **Green lines:** Fully executed

## CI/CD Integration

### GitHub Actions

```yaml
- name: Run tests with coverage
  run: |
    pytest --cov=src --cov-fail-under=80 --cov-report=xml

- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

## Coverage Badge

Add to README.md:

```markdown
![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen)
```

Or use dynamic badge from codecov:

```markdown
[![codecov](https://codecov.io/gh/owner/repo/branch/main/graph/badge.svg)](https://codecov.io/gh/owner/repo)
```

## Identifying Gaps

```bash
# Show uncovered lines
pytest --cov=src --cov-report=term-missing

# Generate report
pytest --cov=src --cov-report=html
# Then examine htmlcov/index.html
```

## Preventing Coverage Decrease

In CI/CD, block PRs if coverage drops:

```bash
pytest --cov=src --cov-fail-under=80
```

This ensures:
- Overall coverage ≥ 80%
- No regression on commits
- Quality maintained over time
