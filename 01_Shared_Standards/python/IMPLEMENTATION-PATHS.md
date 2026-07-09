# Testing Standards Implementation Paths

Visual guide showing how to navigate Agent OS testing standards based on your goals and timeline.

## Quick Decision Tree

```
START HERE
    ↓
Do you have an existing Python project?
    ├─ YES → Go to "Improving Existing Projects"
    └─ NO  → Go to "Starting From Scratch"
```

---

## Starting From Scratch (New Project)

**Timeline:** 30-45 minutes  
**Outcome:** Working test suite with CI/CD

### Path Flow

```
1. SETUP (15 min)
   └─ Create directory structure
   └─ Copy pytest.ini template
   └─ Create conftest.py with fixtures
   └─ Install dependencies

2. WRITE (15 min)
   └─ Create test_example.py
   └─ Add unit tests (AAA pattern)
   └─ Add integration test
   └─ Run pytest locally

3. AUTOMATE (10 min)
   └─ Copy GitHub Actions workflow
   └─ Push to repository
   └─ Verify CI/CD runs

4. MEASURE (5 min)
   └─ Check coverage report
   └─ Aim for 80% baseline
```

### Document Sequence

1. **[Quick-Start Guide](../../03_Templates/prompts/quick-start-testing-setup.md)** (30 min)
   - Step-by-step instructions
   - Copy-paste code examples
   - Common troubleshooting

2. **[Patterns](./unit-testing/patterns.md)** (reference as needed)
   - AAA (Arrange-Act-Assert) pattern
   - Complete working examples

3. **[GitHub Actions](./ci-cd/github-actions.md)** (reference as needed)
   - Workflow configuration
   - Multi-version testing

---

## Improving Existing Projects (2-8 weeks)

**Timeline:** 2 days to 8 weeks (depending on project size)  
**Outcome:** 80%+ coverage, organized tests, automation

### Phase 1: Assessment (1-2 days)

**Goal:** Understand current state

```
measure current coverage
    ↓
run: pytest --cov=src --cov-report=term-missing
    ↓
identify gaps
    ↓
prioritize by business impact
```

**Documents:**
- [Coverage Measurement](./coverage/measurement.md) - How to measure
- [Coverage Requirements](./coverage/requirements.md) - Target by code type

---

### Phase 2: High-Impact Tests (1-2 weeks)

**Goal:** Test critical business logic first

**Recommended order:**
1. Data models (90% target)
2. Business logic (85% target)
3. API endpoints (80% target)
4. Utilities (75% target)

**Documents:**
- [Unit Testing Patterns](./unit-testing/patterns.md) - Basic patterns
- [Naming Conventions](./unit-testing/naming-conventions.md) - Clear test names
- [Assertions](./unit-testing/assertions.md) - Testing best practices
- [Parametrization](./unit-testing/parametrization.md) - Testing multiple scenarios

**Example progression:**
```
Week 1:
  Mon-Tue: Set up pytest, fixtures, conftest
  Wed-Thu: Add tests for data models
  Fri:     Review coverage, fix gaps

Week 2:
  Mon-Wed: Add tests for business logic
  Thu-Fri: Add tests for API endpoints
```

---

### Phase 3: Integration Tests (1-2 weeks)

**Goal:** Test workflows, not just functions

**Choose based on project:**
- [Database Testing](./integration-testing/database-testing.md) - For data-driven projects
- [API Testing](./integration-testing/api-testing.md) - For web services
- [CLI Testing](./integration-testing/cli-testing.md) - For command-line tools
- [Workflow Testing](./integration-testing/workflow-testing.md) - For multi-step processes

**Documents:**
- [Database Testing](./integration-testing/database-testing.md)
- [API Testing](./integration-testing/api-testing.md)
- [CLI Testing](./integration-testing/cli-testing.md)
- [Error Testing](./integration-testing/error-testing.md)

---

### Phase 4: Automation (1 week)

**Goal:** Run tests automatically on every push

**Setup:**
1. Create `.github/workflows/tests.yml`
2. Configure for your Python versions
3. Add coverage reporting to Codecov
4. Add badge to README

**Documents:**
- [GitHub Actions](./ci-cd/github-actions.md) - Complete workflow setup
- [Code Quality](./ci-cd/code-quality.md) - Type checking with mypy
- [Linting & Formatting](./ci-cd/linting-formatting.md) - flake8, black, isort
- [Coverage Reporting](./ci-cd/coverage-reporting.md) - Codecov integration

---

### Phase 5: Polish (1-2 weeks)

**Goal:** Organize, document, and maintain

**Tasks:**
- Organize tests into logical groups
- Update project documentation
- Set up pre-commit hooks
- Train team on patterns
- Establish coverage requirements

**Documents:**
- [Local Development](./environments/local-development.md) - Pre-commit hooks
- [Testing Standard](../testing-standard.md) - Comprehensive overview

---

## Timeline Comparison

### Fast Path (New Project)
```
30-45 minutes total
├─ Setup (15 min)
├─ Write (15 min)
├─ Automate (10 min)
└─ Done: Baseline working tests
```

### Standard Path (Existing Project, < 50K LOC)
```
2 weeks total
├─ Week 1: Assessment + high-impact tests
└─ Week 2: Integration tests + automation
```

### Comprehensive Path (Existing Project, > 50K LOC)
```
8 weeks total
├─ Weeks 1-2: Assessment + high-impact tests
├─ Weeks 3-4: Additional unit test coverage
├─ Weeks 5-6: Integration tests
├─ Weeks 7-8: Automation, polish, team training
```

See: [Full 8-Week Strategy](../../03_Templates/prompts/implement-testing-strategy.md)

---

## By Role

### For Individual Developers

**Get started:**
1. Read: [Patterns](./unit-testing/patterns.md) (10 min)
2. Follow: [Quick-Start Guide](../../03_Templates/prompts/quick-start-testing-setup.md) (30 min)
3. Reference: Specific standards as needed

**Common scenarios:**
- Testing async functions → [Async Testing](./frameworks/async-testing.md)
- Testing with mocks → [Mocking Setup](./frameworks/mocking-setup.md)
- Testing fixtures → [Fixtures Patterns](./frameworks/fixtures-patterns.md)

---

### For Team Leads

**Implement for team:**
1. Share: [Testing Quick-Start](../../TESTING-QUICK-START.md) with team
2. Allocate: 2-8 weeks depending on project size
3. Reference: [Implementation Strategy](../../03_Templates/prompts/implement-testing-strategy.md)
4. Report: [Governance Implementation](../../03_Templates/reports/testing-governance-implementation.md)

**Phased rollout:**
- Week 1: Team reads standards, sets up local environment
- Week 2-4: Implement high-priority tests
- Week 5-6: Add integration tests
- Week 7-8: Automate with CI/CD

---

### For AI Agents

**Implementation flow:**

```
1. Read: Implementation Strategy (full context)
   └─ Understand timeline, scope, roles

2. Choose: Starting or Improving path
   └─ New project: 30-45 min quick setup
   └─ Existing: Phased multi-week approach

3. Reference: Specific standards by need
   └─ Unit testing: patterns.md, naming.md, assertions.md
   └─ Integration: database.md, api.md, workflow.md
   └─ Coverage: measurement.md, requirements.md
   └─ CI/CD: github-actions.md, coverage-reporting.md

4. Execute: Follow patterns, copy templates
   └─ Use examples from this repository
   └─ Validate with pytest
   └─ Check coverage with --cov-report
```

---

## Document Organization

### Quick Reference (Read First)
- [Testing Quick-Start](../../TESTING-QUICK-START.md) - Entry point
- [Implementation Paths](./IMPLEMENTATION-PATHS.md) - This document
- [Quick-Start Guide](../../03_Templates/prompts/quick-start-testing-setup.md) - 30-min setup

### Frameworks (How To)
- [pytest Setup](./frameworks/pytest-setup.md)
- [Fixtures Patterns](./frameworks/fixtures-patterns.md)
- [Mocking Setup](./frameworks/mocking-setup.md)
- [Async Testing](./frameworks/async-testing.md)

### Unit Testing (Fundamentals)
- [Patterns](./unit-testing/patterns.md)
- [Naming Conventions](./unit-testing/naming-conventions.md)
- [Assertions](./unit-testing/assertions.md)
- [Parametrization](./unit-testing/parametrization.md)

### Integration Testing (Workflows)
- [Workflow Testing](./integration-testing/workflow-testing.md)
- [Database Testing](./integration-testing/database-testing.md)
- [API Testing](./integration-testing/api-testing.md)
- [CLI Testing](./integration-testing/cli-testing.md)
- [Error Testing](./integration-testing/error-testing.md)

### Coverage (Measurement)
- [Requirements](./coverage/requirements.md)
- [Measurement](./coverage/measurement.md)
- [Reporting](./coverage/reporting.md)

### Environments (Setup)
- [Local Development](./environments/local-development.md)
- [SQLite Testing](./environments/sqlite-testing.md)
- [Databases](./environments/databases.md)
- [Docker Setup](./environments/docker-setup.md)
- [CI/CD Setup](./environments/ci-cd-setup.md)

### CI/CD (Automation)
- [GitHub Actions](./ci-cd/github-actions.md)
- [Code Quality](./ci-cd/code-quality.md)
- [Linting & Formatting](./ci-cd/linting-formatting.md)
- [Coverage Reporting](./ci-cd/coverage-reporting.md)

### Comprehensive Guides
- [Testing Standard](../testing-standard.md) - Overview
- [Implementation Strategy](../../03_Templates/prompts/implement-testing-strategy.md) - 8-week plan
- [Governance Implementation](../../03_Templates/reports/testing-governance-implementation.md) - Roles & responsibilities

---

## Success Metrics

After implementation, you should have:

- ✅ All test files in `tests/unit/`, `tests/integration/`, `tests/fixtures/`
- ✅ `pytest.ini` configured with coverage tracking
- ✅ `conftest.py` with shared fixtures
- ✅ 80%+ overall code coverage
- ✅ 90%+ coverage on critical code (data models)
- ✅ GitHub Actions workflow running tests on every push
- ✅ All tests follow AAA pattern
- ✅ Clear, descriptive test names
- ✅ No test interdependencies
- ✅ Unit tests < 100ms each

---

## Next Steps

1. **Pick your path:** Starting from scratch vs. improving existing
2. **Choose a document:** From the organization above
3. **Spend 30 minutes:** Get oriented
4. **Spend 30-45 more minutes:** Follow Quick-Start Guide
5. **Start writing tests:** Your first tests this week
6. **Reference standards:** As you encounter specific scenarios

**Questions?** See FAQ in [Testing Quick-Start](../../TESTING-QUICK-START.md)

**Ready to dive in?** → [Quick-Start Guide](../../03_Templates/prompts/quick-start-testing-setup.md)
