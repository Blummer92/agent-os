# Required CI Checks

Before merging:

- [ ] All tests pass
- [ ] Coverage ≥ 80% (≥ 90% for critical modules -- see
      `../coverage/requirements.md`)
- [ ] No test regressions (fail-under enforcement)
- [ ] Flaky tests identified and fixed
- [ ] Test execution time monitored

## Failing Tests

- Must be investigated before merging.
- Cannot merge with skipped/xfail tests except approved exceptions.
- Flaky tests must be fixed or quarantined, not silently retried.
