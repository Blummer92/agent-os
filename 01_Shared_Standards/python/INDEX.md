# Python Testing Standards - Complete Index

This directory contains modular, agent-friendly documentation for Python
testing standards.

### For Quick Start
→ Start with **[environments/local-development.md](environments/local-development.md)**

### For Implementation
→ Use **[frameworks/](frameworks/)** + **[unit-testing/](unit-testing/)** + **[integration-testing/](integration-testing/)**

### For CI/CD
→ See **[ci-cd/](ci-cd/)** for automated testing configuration

---

## Modules (each < 100 lines)

### Testing Frameworks
- **[frameworks/README.md](frameworks/README.md)**, **[pytest-setup.md](frameworks/pytest-setup.md)**,
  **[fixtures-patterns.md](frameworks/fixtures-patterns.md)**,
  **[mocking-setup.md](frameworks/mocking-setup.md)**,
  **[async-testing.md](frameworks/async-testing.md)**

### Unit Testing Standards
- **[unit-testing/README.md](unit-testing/README.md)**, **[patterns.md](unit-testing/patterns.md)**,
  **[naming-conventions.md](unit-testing/naming-conventions.md)**,
  **[assertions.md](unit-testing/assertions.md)**,
  **[parametrization.md](unit-testing/parametrization.md)**,
  **[docstrings.md](unit-testing/docstrings.md)**,
  **[anti-patterns.md](unit-testing/anti-patterns.md)**,
  **[checklist.md](unit-testing/checklist.md)**

### Integration Testing Standards
- **[integration-testing/README.md](integration-testing/README.md)**,
  **[workflow-testing.md](integration-testing/workflow-testing.md)**,
  **[database-testing.md](integration-testing/database-testing.md)**,
  **[api-testing.md](integration-testing/api-testing.md)**,
  **[cli-testing.md](integration-testing/cli-testing.md)**,
  **[error-testing.md](integration-testing/error-testing.md)**

### Code Coverage
- **[coverage/README.md](coverage/README.md)**, **[requirements.md](coverage/requirements.md)**,
  **[measurement.md](coverage/measurement.md)**,
  **[reporting.md](coverage/reporting.md)**

### Test Environment Setup
- **[environments/README.md](environments/README.md)**,
  **[local-development.md](environments/local-development.md)**,
  **[docker-setup.md](environments/docker-setup.md)**,
  **[ci-cd-setup.md](environments/ci-cd-setup.md)**,
  **[databases.md](environments/databases.md)**,
  **[pre-commit-hooks.md](environments/pre-commit-hooks.md)**,
  **[setup-checklist.md](environments/setup-checklist.md)**

### CI/CD Automation
- **[ci-cd/README.md](ci-cd/README.md)**, **[github-actions.md](ci-cd/github-actions.md)**,
  **[gitlab-ci.md](ci-cd/gitlab-ci.md)**,
  **[code-quality.md](ci-cd/code-quality.md)**,
  **[coverage-reporting.md](ci-cd/coverage-reporting.md)**,
  **[required-checks.md](ci-cd/required-checks.md)**

---

## Key Standards

| Standard | Target | Reference |
|----------|--------|-----------|
| Code Coverage | 80% overall, 90% critical | [coverage/requirements.md](coverage/requirements.md) |
| Test Speed | < 100ms unit, < 1s integration | [unit-testing/README.md](unit-testing/README.md) |
| Naming | `test_<what>_<scenario>` | [unit-testing/naming-conventions.md](unit-testing/naming-conventions.md) |
| Pattern | Arrange-Act-Assert | [unit-testing/patterns.md](unit-testing/patterns.md) |
| Framework | pytest 7.0+ | [frameworks/pytest-setup.md](frameworks/pytest-setup.md) |

## Contributing

When adding new documentation: keep files under 100 lines, place in the
appropriate folder, add/update that folder's README.md, and link it here.

## Version
0.2.0
