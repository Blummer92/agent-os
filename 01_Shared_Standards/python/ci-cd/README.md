# CI/CD Standards

## Quick Links

- **[github-actions.md](github-actions.md)** - GitHub Actions workflows
- **[gitlab-ci.md](gitlab-ci.md)** - GitLab CI pipelines
- **[code-quality.md](code-quality.md)** - Linting and formatting
- **[coverage-reporting.md](coverage-reporting.md)** - Coverage metrics
- **[required-checks.md](required-checks.md)** - What must pass before merge

## Overview

Automated testing on every commit ensures:
- No regression
- Consistent quality
- Early error detection
- Clear PR status

## Key Checks

| Check | Tool | Target |
|-------|------|--------|
| Tests | pytest | All tests pass |
| Coverage | pytest-cov | ≥ 80% |
| Linting | flake8 | No violations |
| Formatting | black | Code style |
| Types | mypy | Type safety |

## Workflow Status

Tests run on:
- ✓ Push to main
- ✓ Pull requests
- ✓ Manual trigger

Results shown in:
- ✓ GitHub PR checks
- ✓ Branch protection rules
- ✓ Coverage badges

## Blocking Checks

PRs cannot merge if:
- ✗ Tests fail
- ✗ Coverage drops below 80%
- ✗ Code quality issues found
