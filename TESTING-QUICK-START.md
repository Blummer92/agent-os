# Agent OS Testing Quick Start

Complete guide to understanding and implementing Agent OS testing standards.

## What Is This?

Agent OS provides a comprehensive, modular framework for testing Python projects. This document connects you to the right resource based on your need.

- **Standards**: 39 focused documents covering frameworks, patterns, coverage, and CI/CD
- **Templates**: Ready-to-use boilerplate, example tests, and GitHub Actions workflows
- **Guides**: Step-by-step implementation strategies for individuals and teams

## I Want To...

### Set Up Testing in a New Python Project (30-45 min)

**Start here:** [Quick-Start Testing Setup](./03_Templates/prompts/quick-start-testing-setup.md)

This guide walks you through:
- Creating test directory structure
- Configuring pytest with coverage
- Writing your first unit and integration tests
- Setting up GitHub Actions CI/CD
- Verifying 80%+ coverage

**Duration:** 30-45 minutes  
**Outcome:** Working test suite with coverage tracking and CI/CD

---

### Understand Testing Best Practices (1-2 hours)

**Core concepts:**

1. **[Patterns](./01_Shared_Standards/python/unit-testing/patterns.md)** (10 min)
   - Arrange-Act-Assert (AAA) pattern
   - Complete examples with explanations
   
2. **[Naming Conventions](./01_Shared_Standards/python/unit-testing/naming-conventions.md)** (10 min)
   - `test_<function>_<scenario>` structure
   - Happy path, error case, and exception examples
   
3. **[Assertions](./01_Shared_Standards/python/unit-testing/assertions.md)** (15 min)
   - pytest assertions vs basic assert
   - Testing exceptions with `pytest.raises`
   - Grouping related assertions
   
4. **[Parametrization](./01_Shared_Standards/python/unit-testing/parametrization.md)** (15 min)
   - Testing multiple scenarios with `@pytest.mark.parametrize`
   - Dynamic parameters and fixtures

5. **[Fixtures & Mocking](./01_Shared_Standards/python/frameworks/fixtures-patterns.md)** (15 min)
   - Fixture scopes (function, class, session)
   - Setup and cleanup patterns
   - See also: [Mocking Setup](./01_Shared_Standards/python/frameworks/mocking-setup.md)

**Total:** 65 minutes  
**Outcome:** Confident writing testable, well-organized tests

---

### Set Up Coverage Tracking (15 min)

**Quick path:**

1. Install: `pip install pytest-cov`
2. Run: `pytest --cov=src --cov-report=html`
3. Open: `htmlcov/index.html`

**For details:** [Coverage Measurement](./01_Shared_Standards/python/coverage/measurement.md)

**Coverage targets:**
- Overall: 80% minimum
- Critical/data models: 90%
- Business logic: 85%
- Utilities: 75%

See: [Coverage Requirements](./01_Shared_Standards/python/coverage/requirements.md)

---

### Configure CI/CD with GitHub Actions (20 min)

**Quick path:**

1. Copy: [Sample workflow](./03_Templates/python-project-template/.github_workflows_tests.yml)
2. Save as: `.github/workflows/tests.yml`
3. Customize: Python versions, test paths
4. Push: Workflow runs automatically on push/PR

**For details:** [GitHub Actions](./01_Shared_Standards/python/ci-cd/github-actions.md)

**Features included:**
- Multi-version Python testing (3.9-3.12)
- Coverage reporting to Codecov
- Automatic badge generation
- Matrix testing for dependencies

---

### Improve Existing Test Suite (2-4 weeks)

**Phased approach:**

**Week 1-2: Assessment**
- Measure current coverage
- Identify gaps (lines without tests)
- Prioritize high-value areas

**Week 3-4: Implementation**
- Follow [Patterns](./01_Shared_Standards/python/unit-testing/patterns.md)
- Focus on critical code first (90%)
- Then business logic (85%)
- Finally utilities (75%)

**Week 5-6: Integration Tests**
- Add [Integration tests](./01_Shared_Standards/python/integration-testing/) for workflows
- Test database interactions
- Test API endpoints
- Test CLI commands

**Week 7-8: CI/CD & Polish**
- Set up GitHub Actions
- Add coverage badges
- Document test patterns
- Train team

See: [Full 8-Week Strategy](./03_Templates/prompts/implement-testing-strategy.md)

---

### Test Async/Await Code (10 min)

**Quick guide:** [Async Testing](./01_Shared_Standards/python/frameworks/async-testing.md)

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await my_async_function()
    assert result == expected
```

---

### Test Database Code (20 min)

**Database testing:**
- SQLite in-memory for speed: [SQLite Testing](./01_Shared_Standards/python/environments/sqlite-testing.md)
- PostgreSQL with containers: [Databases](./01_Shared_Standards/python/environments/databases.md)
- Docker setup: [Docker Setup](./01_Shared_Standards/python/environments/docker-setup.md)

---

### Test CLI Commands (15 min)

**CLI testing patterns:** [CLI Testing](./01_Shared_Standards/python/integration-testing/cli-testing.md)

Example with Click:
```python
from click.testing import CliRunner

def test_cli_command():
    runner = CliRunner()
    result = runner.invoke(my_command, ['--option', 'value'])
    assert result.exit_code == 0
    assert 'expected output' in result.output
```

---

### Test API Endpoints (20 min)

**API testing patterns:** [API Testing](./01_Shared_Standards/python/integration-testing/api-testing.md)

Example with FastAPI:
```python
from fastapi.testclient import TestClient

def test_api_endpoint(client):
    response = client.get("/api/users/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1
```

---

### Set Up Local Development Environment (30 min)

**Complete setup guide:** [Local Development](./01_Shared_Standards/python/environments/local-development.md)

Includes:
- Virtual environment creation
- Dependency installation
- Running tests locally
- Pre-commit hooks
- IDE integration

---

### Get My Team On Board (2-3 days)

**Team implementation guide:**

1. **Day 1:** Team reads this document + [Quick-Start Guide](./03_Templates/prompts/quick-start-testing-setup.md)
2. **Day 2:** Each person sets up testing in their current project
3. **Day 3:** Review patterns, discuss approach, establish team practices

**Reference materials:**
- [Testing Governance](./03_Templates/reports/testing-governance-implementation.md) - Roles and responsibilities
- [Implementation Strategy](./03_Templates/prompts/implement-testing-strategy.md) - 8-week rollout plan
- All standards in [01_Shared_Standards/python/](./01_Shared_Standards/python/) - Detailed guidance

---

## Document Map

### Standards (39 documents organized by topic)

**[01_Shared_Standards/python/](./01_Shared_Standards/python/)**

- **Frameworks** - pytest, fixtures, mocking, async
- **Unit Testing** - patterns, naming, assertions, parametrization
- **Integration Testing** - workflows, databases, APIs, CLI, errors
- **Coverage** - requirements, measurement, reporting
- **Environments** - local dev, SQLite, databases, Docker, CI/CD
- **CI/CD** - GitHub Actions, quality checks, linting, coverage

Browse all: [INDEX.md](./01_Shared_Standards/python/INDEX.md)

### Templates (Ready-to-use files)

**[03_Templates/](./03_Templates/)**

- **Quick-Start Guide** - 30-45 min setup for new projects
- **Full Implementation Strategy** - 8-week rollout
- **Project Template** - pytest.ini, conftest.py, examples
- **GitHub Actions Workflow** - Multi-version testing
- **Report Templates** - Progress, governance, testing

### Examples

**In this repository:**

- [tests/conftest.py](./tests/conftest.py) - 20+ shared fixtures
- [tests/unit/test_standards_exist.py](./tests/unit/test_standards_exist.py) - Comprehensive examples
- [tests/integration/test_governance_workflow.py](./tests/integration/test_governance_workflow.py) - Integration patterns

---

## Common Questions

**Q: Where do I start with no testing experience?**
A: Read [Patterns](./01_Shared_Standards/python/unit-testing/patterns.md) (10 min), then use [Quick-Start Guide](./03_Templates/prompts/quick-start-testing-setup.md) (30 min).

**Q: How much coverage do I need?**
A: 80% minimum overall. 90% for critical code (data models), 85% for business logic, 75% for utilities. See [Coverage Requirements](./01_Shared_Standards/python/coverage/requirements.md).

**Q: Can I use these standards in an existing project?**
A: Yes! Use [Quick-Start Guide](./03_Templates/prompts/quick-start-testing-setup.md) as a checklist, then gradually add tests to reach 80% coverage.

**Q: How do I test async functions?**
A: Use `@pytest.mark.asyncio` decorator. See [Async Testing](./01_Shared_Standards/python/frameworks/async-testing.md).

**Q: How do I mock external dependencies?**
A: Use `pytest-mock` plugin. See [Mocking Setup](./01_Shared_Standards/python/frameworks/mocking-setup.md).

**Q: How do I set up GitHub Actions?**
A: Copy the workflow from [03_Templates/python-project-template/.github_workflows_tests.yml](./03_Templates/python-project-template/.github_workflows_tests.yml) and save as `.github/workflows/tests.yml`.

**Q: What if I'm an AI agent implementing tests for a project?**
A: Read [Implementation Strategy](./03_Templates/prompts/implement-testing-strategy.md) for context, then use appropriate standards documents. Reference the examples in this repository.

---

## Key Statistics

- **39 standards documents** across 6 categories
- **12 ready-to-use templates** (pytest configs, test examples, CI/CD)
- **87% of documents < 100 lines** (optimized for agent readability)
- **Complete code examples** in every standards document
- **62 validation tests** ensuring all standards exist and are complete
- **Zero breaking changes** when deployed to existing projects

---

## Next Steps

1. **Pick your starting point** from "I Want To..." section above
2. **Spend 30-45 minutes** with the Quick-Start Guide
3. **Run your first tests** with pytest
4. **Reference standards documents** as needed for specific scenarios
5. **Set up CI/CD** to automate testing on every push
6. **Reach 80% coverage** gradually, starting with high-value code

---

**Questions or feedback?**

See the issue tracker for known limitations. All standards are open to refinement based on team experience.

**Last updated:** July 2026  
**Framework versions:** pytest 7.0+, Python 3.9-3.12  
**Coverage baseline:** 80% minimum, automated in CI/CD
