# Implement Testing Strategy for Agent OS

Guides implementation of the Agent OS Python Testing Standard in a
project. Each phase points to the relevant standard instead of repeating
its content -- see `01_Shared_Standards/python/INDEX.md` for the full set.

## Phase 1: Foundation Setup
- [ ] Create `tests/{unit,integration,fixtures,e2e}` + `__init__.py` files
- [ ] Copy `pytest.ini` and `tests/conftest.py` from
      `03_Templates/python-project-template/`
- [ ] Add pytest + plugins to `requirements-dev.txt` (see
      `frameworks/pytest-setup.md`)
- [ ] Verify: `pytest --collect-only` finds 0 tests (not yet written)

## Phase 2: Unit Tests
- [ ] List core modules in priority order (validators, models, utils, CLI)
- [ ] Write `tests/unit/test_<module>.py` per module (see
      `unit-testing/patterns.md`, `unit-testing/naming-conventions.md`)
- [ ] Run `pytest tests/unit --cov=src --cov-report=html`, meet targets
      in `coverage/requirements.md`
- [ ] Checklist: independent, deterministic, fast (< 100ms) -- see
      `unit-testing/checklist.md`

## Phase 3: Integration Tests
- [ ] List critical workflows (data flow, CLI, DB, file processing, API)
- [ ] Write `tests/integration/test_<workflow>.py` (see
      `integration-testing/workflow-testing.md` and siblings)
- [ ] Set up DB/file/API fixtures (see
      `integration-testing/database-testing.md`)
- [ ] Run `pytest -m integration`, mark tests `@pytest.mark.integration`

## Phase 4: CI/CD
- [ ] Copy `.github_workflows_tests.yml` to `.github/workflows/tests.yml`
      (see `ci-cd/github-actions.md`, or `ci-cd/gitlab-ci.md`)
- [ ] Confirm required checks: tests pass, coverage threshold, lint/type
      checks (see `ci-cd/required-checks.md`)
- [ ] Open a PR and verify CI runs and blocks on failure

## Phase 5: Documentation
- [ ] Add a testing section to the project README (quick-start commands,
      coverage, link to standards)
- [ ] Add testing requirements to the contributing guide (min coverage,
      naming, framework)

## Phase 6: Governance Integration
- [ ] Record which standards and versions this project follows (see
      `04_Registry/module-version-map.md` for current versions)
- [ ] Document coverage targets, test environment, and required CI
      checks for this project
- [ ] Link back to `01_Shared_Standards/python/` from the project's docs

## Phase 7: Ongoing Maintenance
- [ ] Add a regression test for every bug fix (reproduce, fix, verify,
      commit together)
- [ ] Review coverage monthly; review test strategy quarterly
- [ ] Keep tests fast -- `pytest --durations=10` to find slow ones, mock
      expensive I/O, mark genuinely slow tests `@pytest.mark.slow`

## Success Criteria
Coverage >= 80% overall (>= 90% critical modules); full suite < 5
minutes; tests run on every commit; no unapproved skipped/xfail tests;
aligned with the standards in `01_Shared_Standards/python/`.

## Troubleshooting
Tests won't run → `pip install pytest pytest-cov pytest-mock`, check
`pytest --collect-only` and `PYTHONPATH`. Coverage too low → `pytest
--cov=src --cov-report=html`, review `htmlcov/index.html`. Flaky tests →
check for interdependencies, hardcoded timing, or unseeded randomness.

## Resources
- `01_Shared_Standards/python/INDEX.md` -- full standards index
- `03_Templates/python-project-template/` -- starter files
