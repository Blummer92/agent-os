# Python Standards

Quick references for Python development in Agent OS.

## Testing Standards (Modular)

The testing standards are now organized into **37 small, focused documents** organized by topic:

### Get Started
- **[environments/local-development.md](environments/local-development.md)** - Set up testing locally in 5 minutes

### Documentation Structure

| Category | Purpose | Files |
|----------|---------|-------|
| **[frameworks/](frameworks/)** | pytest, fixtures, mocking, async | 5 documents |
| **[unit-testing/](unit-testing/)** | Unit test patterns and best practices | 5 documents |
| **[integration-testing/](integration-testing/)** | Workflow, database, API, CLI testing | 5 documents |
| **[coverage/](coverage/)** | Coverage requirements and reporting | 4 documents |
| **[environments/](environments/)** | Local, Docker, CI/CD setup | 5 documents |
| **[ci-cd/](ci-cd/)** | GitHub Actions and code quality | 4 documents |

### Complete Index

→ See **[INDEX.md](INDEX.md)** for complete navigation

## Key Standards

- **Coverage:** 80% minimum (90% for critical code)
- **Framework:** pytest 7.0+
- **Test speed:** < 100ms unit tests, < 1s integration
- **Naming:** `test_<what>_<scenario>`
- **Pattern:** Arrange-Act-Assert (AAA)
- **Python versions:** 3.9, 3.10, 3.11, 3.12

## Quick Start

```bash
# Set up locally (5 minutes)
1. Read: environments/local-development.md
2. Install: pip install -r requirements-dev.txt
3. Run: pytest tests/ -v

# Write unit tests
1. Read: unit-testing/patterns.md
2. Follow: AAA pattern (Arrange-Act-Assert)
3. Check: unit-testing/naming-conventions.md

# Set up CI/CD
1. Read: ci-cd/github-actions.md
2. Create: .github/workflows/tests.yml
3. Enable: GitHub branch protection rules
```

## Architecture

Each document is **< 100 lines** and focused on a single topic:

- **frameworks/** - pytest and testing tools
- **unit-testing/** - Unit test standards
- **integration-testing/** - Integration test standards
- **coverage/** - Code coverage requirements
- **environments/** - Test environment setup
- **ci-cd/** - Automated testing and quality checks

→ Start with a folder's README.md for navigation

## Version

- **Structure:** 1.0 (Modular, agent-friendly)
- **Coverage:** 80% minimum, 90% critical
- **Python:** 3.9+
