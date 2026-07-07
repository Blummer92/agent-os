# Implement Testing Strategy for Agent OS

## Overview
This prompt guides implementation of Agent OS testing standards in a Python project. It provides a step-by-step strategy to add comprehensive testing coverage aligned with governance standards.

## Phase 1: Foundation Setup (Week 1)

### Step 1.1: Create Test Directory Structure
```bash
mkdir -p tests/{unit,integration,fixtures,e2e}
touch tests/__init__.py
touch tests/unit/__init__.py
touch tests/integration/__init__.py
touch tests/fixtures/__init__.py
```

### Step 1.2: Set Up pytest Configuration
- Copy `pytest.ini` from templates
- Create `tests/conftest.py` from `test_conftest.py` template
- Add pytest to `requirements-dev.txt`

**Files to create/modify:**
- `pytest.ini` - pytest configuration
- `tests/conftest.py` - shared fixtures
- `requirements-dev.txt` - dev dependencies

**Validation:**
```bash
pytest --collect-only  # Should find 0 tests (yet)
```

### Step 1.3: Create pyproject.toml Coverage Config
```toml
[tool.coverage.run]
source = ["src"]
branch = true
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if __name__ == .__main__.:",
]
```

### Step 1.4: Set Up Development Dependencies
```bash
pip install -r requirements-dev.txt
```

**Checklist:**
- [ ] Test directory structure created
- [ ] pytest.ini in place
- [ ] tests/conftest.py created with fixtures
- [ ] requirements-dev.txt updated
- [ ] pytest runs successfully (0 tests)

---

## Phase 2: Add Unit Tests (Weeks 1-2)

### Step 2.1: Identify Core Modules to Test
List modules in priority order:
1. Validators and business logic
2. Data models/classes
3. Core utilities
4. CLI commands

### Step 2.2: Write Unit Tests for Core Modules

For each module, create `tests/unit/test_<module>.py`:
```bash
# Example structure
tests/unit/test_validators.py
tests/unit/test_models.py
tests/unit/test_cli.py
tests/unit/test_utils.py
```

**Use template:** `test_unit_template.py`

**Target coverage per module:**
- Validators: 90%+
- Models: 85%+
- Utils: 80%+
- CLI: 80%+

### Step 2.3: Run Tests and Check Coverage
```bash
pytest tests/unit --cov=src --cov-report=html
# Open htmlcov/index.html to see coverage
```

**Target:** 80% overall coverage minimum

**Checklist:**
- [ ] Unit tests written for all core modules
- [ ] Coverage >= 80%
- [ ] All tests passing
- [ ] No test interdependencies
- [ ] Tests are fast (< 100ms each)

---

## Phase 3: Add Integration Tests (Week 2)

### Step 3.1: Identify Workflows to Test
List critical workflows:
1. End-to-end data flow
2. CLI command execution
3. Database operations (if applicable)
4. File processing
5. API integration (if applicable)

### Step 3.2: Write Integration Tests

Create `tests/integration/test_<workflow>.py`:
```bash
tests/integration/test_workflows.py
tests/integration/test_cli.py
tests/integration/test_database.py  # if applicable
```

**Use template:** `test_integration_template.py`

### Step 3.3: Set Up Integration Test Fixtures

Create `tests/conftest.py` additions or `tests/integration/conftest.py`:
- Database fixtures
- File system fixtures
- Mock API fixtures

### Step 3.4: Run Integration Tests
```bash
pytest tests/integration --cov=src --cov-append
pytest -m integration  # Run only integration tests
```

**Checklist:**
- [ ] Integration tests written for workflows
- [ ] Database fixtures working
- [ ] External APIs mocked
- [ ] Tests marked with @pytest.mark.integration
- [ ] Tests under 1 second each

---

## Phase 4: CI/CD Setup (Week 2-3)

### Step 4.1: Create GitHub Actions Workflow

```bash
mkdir -p .github/workflows
cp .github_workflows_tests.yml .github/workflows/tests.yml
```

### Step 4.2: Configure Test Automation

The workflow includes:
- Unit tests (fast)
- Integration tests (slower)
- Code quality checks (black, flake8, mypy)
- Coverage reporting
- Test result publishing

### Step 4.3: Test CI/CD Pipeline

1. Push changes to a feature branch
2. Create pull request
3. Verify tests run automatically
4. Check coverage report

**Checklist:**
- [ ] GitHub Actions workflow configured
- [ ] Tests run on push
- [ ] Tests required for PR merge
- [ ] Coverage reports generated
- [ ] CI status visible on PRs

---

## Phase 5: Documentation (Week 3)

### Step 5.1: Create Testing Guide

Document project-specific testing:
```markdown
# Testing Guide

## Running Tests

### Local Development
- pytest
- pytest --cov

### Specific Test Types
- pytest -m "not slow and not integration"
- pytest -m integration

## Writing Tests

See [Agent OS Testing Standards](../../01_Shared_Standards/python/testing-standard.md)

### Project Structure
- tests/unit/ - unit tests
- tests/integration/ - integration tests
- tests/fixtures/ - shared test data

### Database Setup
[Project-specific DB setup]

### Common Issues
[Project-specific troubleshooting]
```

### Step 5.2: Update README

Add testing section:
```markdown
## Testing

### Quick Start
```bash
pytest
pytest --cov  # with coverage
```

### View Coverage
```bash
pytest --cov
open htmlcov/index.html
```

### Running Specific Tests
```bash
pytest tests/unit/test_validators.py
pytest -m integration
```

See [Testing Guide](TESTING.md) for details.
```

### Step 5.3: Update Contributing Guide

Add testing requirements:
```markdown
## Testing Requirements

- All new features must include tests
- Minimum coverage: 80%
- All tests must pass before merge
- Use pytest framework and fixtures
- Follow naming conventions

See [Agent OS Testing Standards](../) for details.
```

**Checklist:**
- [ ] TESTING.md created with project-specific guidance
- [ ] README includes testing section
- [ ] Contributing guide updated with test requirements
- [ ] Testing standards linked in documentation

---

## Phase 6: Governance Integration (Week 3)

### Step 6.1: Create Project Testing Profile

Create `PROJECT_TESTING.md`:
```markdown
# Project Testing Profile

## Standards Applied
- Python Testing Standard v0.2.0
- Unit Testing Standard v0.1.0
- Integration Testing Standard v0.1.0
- Test Environment Setup v0.1.0

## Coverage Targets
- Overall: 80%
- Validators: 90%+
- Models: 85%+
- Utils: 80%+

## Test Environment
- Framework: pytest
- Database: [PostgreSQL/SQLite]
- External APIs: Mocked with unittest.mock

## CI/CD
- GitHub Actions (see .github/workflows/tests.yml)
- Required checks before merge:
  - pytest passes
  - Coverage >= 80%
  - Flake8/mypy checks pass

## Key Test Files
- tests/conftest.py - shared fixtures
- tests/unit/ - unit tests (fast)
- tests/integration/ - integration tests (slower)

## Maintenance
- Review test coverage monthly
- Update tests when bugs are found
- Refactor tests with code changes
```

### Step 6.2: Link to Agent OS Standards

In project README or docs:
```markdown
## Governance

This project follows:
- [Agent OS Python Testing Standard](../../01_Shared_Standards/python/testing-standard.md)
- [Agent OS Unit Testing Standard](../../01_Shared_Standards/python/unit-testing-standard.md)
- [Agent OS Integration Testing Standard](../../01_Shared_Standards/python/integration-testing-standard.md)
```

**Checklist:**
- [ ] PROJECT_TESTING.md created
- [ ] Standards linked in documentation
- [ ] Coverage targets documented
- [ ] Test environment described
- [ ] CI/CD process documented

---

## Phase 7: Ongoing Maintenance (Continuous)

### Step 7.1: Regression Testing

When bugs are found:
1. Write test that reproduces bug (fails)
2. Fix code
3. Verify test passes
4. Commit test with fix

Example:
```python
def test_validator_handles_null_bytes_regression_issue_123():
    """Regression test for issue #123."""
    invalid_email = "test\x00@example.com"
    result = validate_email(invalid_email)
    assert result.is_valid is False
```

### Step 7.2: Coverage Maintenance

**Monthly:**
- `pytest --cov` to check coverage
- Address any significant regressions
- Review test quality

**Quarterly:**
- Review test strategy
- Identify areas for improvement
- Update standards if needed

### Step 7.3: Keep Tests Fast

**Guidelines:**
- Unit tests: < 100ms each
- Integration tests: < 1s each
- Full suite: < 5 minutes

**If tests slow down:**
1. Identify slow tests: `pytest --durations=10`
2. Mock expensive operations
3. Use in-memory databases
4. Mark slow tests: `@pytest.mark.slow`

**Checklist:**
- [ ] Regression tests added for bugs
- [ ] Coverage reviewed monthly
- [ ] Tests remain fast
- [ ] Test quality maintained

---

## Implementation Checklist

### Week 1: Foundation
- [ ] Test directory structure created
- [ ] pytest configured
- [ ] requirements-dev.txt updated
- [ ] Unit tests written (aim for 80%+ coverage)

### Week 2: Integration & Quality
- [ ] Integration tests written
- [ ] Database/API fixtures working
- [ ] GitHub Actions workflow set up
- [ ] Coverage reports working

### Week 3: Documentation & Governance
- [ ] Testing guide documentation created
- [ ] README updated with testing section
- [ ] Contributing guide updated
- [ ] Project testing profile created
- [ ] Standards linked in docs

### Ongoing
- [ ] Regression tests added for bugs
- [ ] Coverage maintained >= 80%
- [ ] Tests remain fast
- [ ] Quality reviews monthly

---

## Success Criteria

✓ **Coverage:** >= 80% overall, >= 90% for critical modules
✓ **Speed:** Full test suite runs in < 5 minutes
✓ **Automation:** Tests run on every commit
✓ **Quality:** No skipped/xfail tests without approval
✓ **Documentation:** Clear guidance for developers
✓ **Governance:** Aligned with Agent OS standards

---

## Troubleshooting

### Tests won't run
```bash
# Check pytest is installed
pip install pytest pytest-cov pytest-mock

# Verify tests are discoverable
pytest --collect-only

# Check Python path
export PYTHONPATH=src:$PYTHONPATH
```

### Coverage too low
- Use `pytest --cov=src --cov-report=html`
- Review uncovered lines in htmlcov/index.html
- Add tests for missing coverage
- Consider `# pragma: no cover` for uncoverable code

### Flaky tests
- Check for test interdependencies
- Avoid hardcoded timing
- Use fixtures for setup/teardown
- Verify database isolation
- Seed random number generators

### Slow tests
- Run `pytest --durations=10` to find slow tests
- Mock expensive I/O operations
- Use in-memory databases
- Consider `@pytest.mark.slow` for integration tests

### CI/CD failures
- Run tests locally: `pytest`
- Check environment variables set in CI
- Verify database/service availability
- Review CI logs for error messages

---

## Next Steps

1. Follow Phase 1-7 in order
2. Reference templates in `03_Templates/python-project-template/`
3. Link to standards in `01_Shared_Standards/python/`
4. Document project-specific testing in PROJECT_TESTING.md
5. Schedule monthly coverage reviews

## Resources

- [Python Testing Standard](../../01_Shared_Standards/python/testing-standard.md)
- [Unit Testing Standard](../../01_Shared_Standards/python/unit-testing-standard.md)
- [Integration Testing Standard](../../01_Shared_Standards/python/integration-testing-standard.md)
- [Test Environment Setup](../../01_Shared_Standards/python/test-environment-setup.md)
- Templates: [Python Project Template](../python-project-template/)
