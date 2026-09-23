# Environment Setup Checklist

- [ ] Virtual environment created and activated
- [ ] Test dependencies installed (`requirements-dev.txt`)
- [ ] `pytest.ini` configured (see `../frameworks/pytest-setup.md`)
- [ ] `tests/conftest.py` created with root fixtures
- [ ] CI/CD workflow configured (see `../ci-cd/github-actions.md` or
      `../ci-cd/gitlab-ci.md`)
- [ ] Database fixtures set up for integration tests (see
      `../integration-testing/database-testing.md`)
- [ ] Environment variables configured (`.env.test`)
- [ ] Mock API/external service fixtures created (see
      `../frameworks/mocking-setup.md`)
- [ ] Docker setup for consistent environments (see `docker-setup.md`)
- [ ] Optional pre-commit hooks configured (see `pre-commit-hooks.md`)
- [ ] Agent OS protected-branch safeguard installed with
      `python scripts/protected_branch_push_guard.py install`
- [ ] Safeguard status verified with
      `python scripts/protected_branch_push_guard.py status`
- [ ] Existing local `core.hooksPath` preserved or any conflict resolved manually
- [ ] Removal command and emergency-approval boundary understood
- [ ] Coverage reporting configured (see `../coverage/reporting.md`)
- [ ] Database cleanup procedures in place
