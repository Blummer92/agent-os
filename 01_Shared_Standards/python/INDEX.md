# Python Testing Standards - Complete Index

This directory contains modular, agent-friendly documentation for Python testing standards.

## Quick Navigation

### For Quick Start
→ Start with **[environments/local-development.md](environments/local-development.md)** to set up locally

### For Implementation
→ Use **[frameworks/](frameworks/)** + **[unit-testing/](unit-testing/)** + **[integration-testing/](integration-testing/)**

### For CI/CD
→ See **[ci-cd/](ci-cd/)** for automated testing configuration

---

## Core Modules (< 100 lines each)

### Testing Frameworks
- **[frameworks/README.md](frameworks/README.md)** - Overview of pytest and tools
- **[frameworks/pytest-setup.md](frameworks/pytest-setup.md)** - pytest.ini configuration
- **[frameworks/fixtures-patterns.md](frameworks/fixtures-patterns.md)** - Reusable test setup
- **[frameworks/mocking-setup.md](frameworks/mocking-setup.md)** - External dependency mocking
- **[frameworks/async-testing.md](frameworks/async-testing.md)** - Async/await test patterns

### Unit Testing Standards
- **[unit-testing/README.md](unit-testing/README.md)** - Unit test overview
- **[unit-testing/patterns.md](unit-testing/patterns.md)** - AAA pattern (Arrange-Act-Assert)
- **[unit-testing/naming-conventions.md](unit-testing/naming-conventions.md)** - Test naming rules
- **[unit-testing/assertions.md](unit-testing/assertions.md)** - Writing good assertions
- **[unit-testing/parametrization.md](unit-testing/parametrization.md)** - Parameterized tests

### Integration Testing Standards
- **[integration-testing/README.md](integration-testing/README.md)** - Integration test overview
- **[integration-testing/workflow-testing.md](integration-testing/workflow-testing.md)** - End-to-end workflows
- **[integration-testing/database-testing.md](integration-testing/database-testing.md)** - Database testing
- **[integration-testing/api-testing.md](integration-testing/api-testing.md)** - API endpoint testing
- **[integration-testing/cli-testing.md](integration-testing/cli-testing.md)** - CLI command testing
- **[integration-testing/error-testing.md](integration-testing/error-testing.md)** - Error scenarios

### Code Coverage
- **[coverage/README.md](coverage/README.md)** - Coverage overview
- **[coverage/requirements.md](coverage/requirements.md)** - Coverage targets (80%/90%)
- **[coverage/measurement.md](coverage/measurement.md)** - How to measure coverage
- **[coverage/reporting.md](coverage/reporting.md)** - Coverage reports and CI/CD

### Test Environment Setup
- **[environments/README.md](environments/README.md)** - Environment overview
- **[environments/local-development.md](environments/local-development.md)** - Local machine setup
- **[environments/docker-setup.md](environments/docker-setup.md)** - Docker containers
- **[environments/ci-cd-setup.md](environments/ci-cd-setup.md)** - CI/CD automation
- **[environments/databases.md](environments/databases.md)** - Database configuration

### CI/CD Automation
- **[ci-cd/README.md](ci-cd/README.md)** - CI/CD overview
- **[ci-cd/github-actions.md](ci-cd/github-actions.md)** - GitHub Actions workflows
- **[ci-cd/code-quality.md](ci-cd/code-quality.md)** - Linting and formatting
- **[ci-cd/coverage-reporting.md](ci-cd/coverage-reporting.md)** - Coverage tracking

---

## File Statistics

- **Total files:** 37 markdown documents
- **Modular structure:** 6 main categories
- **Each file:** ~50-100 lines (agent-friendly)
- **Easy navigation:** Organized by topic and use case

---

## How to Use This Documentation

### I want to...

**...set up testing locally**
1. [environments/local-development.md](environments/local-development.md) - Step 1: Setup
2. [frameworks/pytest-setup.md](frameworks/pytest-setup.md) - Step 2: Configure pytest
3. [unit-testing/patterns.md](unit-testing/patterns.md) - Step 3: Write unit tests

**...write better unit tests**
1. [unit-testing/patterns.md](unit-testing/patterns.md) - Learn AAA pattern
2. [unit-testing/naming-conventions.md](unit-testing/naming-conventions.md) - Use good names
3. [unit-testing/assertions.md](unit-testing/assertions.md) - Write assertions
4. [frameworks/fixtures-patterns.md](frameworks/fixtures-patterns.md) - Set up test data

**...test a complete workflow**
1. [integration-testing/workflow-testing.md](integration-testing/workflow-testing.md) - Multi-component testing
2. [integration-testing/database-testing.md](integration-testing/database-testing.md) - Database interactions
3. [integration-testing/error-testing.md](integration-testing/error-testing.md) - Error scenarios

**...set up automated testing**
1. [ci-cd/github-actions.md](ci-cd/github-actions.md) - Create workflow file
2. [ci-cd/code-quality.md](ci-cd/code-quality.md) - Add quality checks
3. [ci-cd/coverage-reporting.md](ci-cd/coverage-reporting.md) - Track coverage

**...mock external dependencies**
1. [frameworks/mocking-setup.md](frameworks/mocking-setup.md) - Mock strategies
2. [frameworks/fixtures-patterns.md](frameworks/fixtures-patterns.md) - Fixture patterns

**...test async code**
1. [frameworks/async-testing.md](frameworks/async-testing.md) - Async test patterns

---

## Key Standards

| Standard | Target | Reference |
|----------|--------|-----------|
| Code Coverage | 80% overall, 90% critical | [coverage/requirements.md](coverage/requirements.md) |
| Test Speed | < 100ms unit, < 1s integration | [unit-testing/README.md](unit-testing/README.md) |
| Naming | `test_<what>_<scenario>` | [unit-testing/naming-conventions.md](unit-testing/naming-conventions.md) |
| Pattern | Arrange-Act-Assert | [unit-testing/patterns.md](unit-testing/patterns.md) |
| Framework | pytest 7.0+ | [frameworks/pytest-setup.md](frameworks/pytest-setup.md) |

---

## Version Information

- **Python:** 3.9, 3.10, 3.11, 3.12
- **pytest:** 7.0.0+
- **pytest-cov:** 4.0.0+
- **Date:** 2024

---

## Contributing

When adding new documentation:
1. Keep files < 100 lines
2. Place in appropriate folder
3. Add README.md to folder
4. Update this INDEX.md
5. Link from folder README

---

## Legacy Files

The following files are consolidated into the modular structure:
- `testing-standard.md` → See [frameworks/](frameworks/) + [unit-testing/](unit-testing/)
- `unit-testing-standard.md` → See [unit-testing/](unit-testing/)
- `integration-testing-standard.md` → See [integration-testing/](integration-testing/)
- `test-environment-setup.md` → See [environments/](environments/) + [ci-cd/](ci-cd/)

All content has been preserved and reorganized for clarity.
