# Test Quality Checklist

Before merging, confirm:

- [ ] Tests are independent (no ordering dependency)
- [ ] Tests are deterministic (no flakiness)
- [ ] Fixtures are used for setup/teardown
- [ ] External services are mocked (see `frameworks/mocking-setup.md`)
- [ ] Coverage targets met (see `coverage/requirements.md`)
- [ ] Test names describe what is tested (see `naming-conventions.md`)
- [ ] Tests follow the AAA pattern (see `patterns.md`)
- [ ] No hardcoded paths or credentials
- [ ] Async tests use `@pytest.mark.asyncio`
- [ ] Regression tests added for bug fixes
- [ ] No anti-patterns present (see `anti-patterns.md`)

See `../ci-cd/required-checks.md` for what CI itself enforces on top of
this checklist.
