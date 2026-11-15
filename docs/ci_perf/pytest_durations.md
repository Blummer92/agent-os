# Optional pytest duration reporting

Issue: #3695. Measurement owner: #520. Aggregate/suite timing owner: completed #1359.

Use pytest's built-in duration report during the test execution you already need.
No adapter, plugin, runner change, mandatory check or second timing-only test run
is needed. The report is advisory and does not satisfy aggregate validation.

## Local reproduction

From the repository root, append the two reporting flags to the same focused
pytest invocation you would otherwise run:

```bash
python -m pytest tests/agent_os_issue_acceptance/test_readiness.py --durations=20 --durations-min=0
```

Keep the original test targets, selection/order options, coverage arguments,
working directory, environment and interpreter. For an installed package suite,
keep its existing `PYTHONPATH=src` and `--cov` / `--cov-report` arguments; append
only `--durations=20 --durations-min=0`. Do not replace the canonical validation
command with a focused test when authoritative validation is required.

`--durations=20` ranks the 20 slowest individual setup, call and teardown reports,
not necessarily 20 distinct tests. Shared fixtures are charged to the setup or
teardown of the test that initializes/finalizes them; this is not independent
per-fixture attribution. `--durations-min=0` prevents the threshold from hiding
short phases, but a phase can still fall outside the top 20. If fixture phases
are absent from the ranking, choose a larger bound (or `--durations=0` for all
phases) **before the next already-required execution**. Do not rerun a suite
merely to obtain more timing output. Console durations round to two decimal
places: `0.00s` is not evidence of zero cost.

For the unchanged aggregate runner, an optional local environment setting can
apply the reporting flags to its existing pytest executions:

```bash
PYTEST_ADDOPTS="${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS }--durations=20 --durations-min=0" bash scripts/validate-all.sh
```

This preserves any existing `PYTEST_ADDOPTS` value and changes no repository
configuration. Prefer the direct focused invocation for routine diagnosis; use
aggregate execution only when already required. Keep the command's exit status:
redirection preserves it, whereas an unguarded pipe to `tee` can mask failures.
The reporting flags do not change pytest collection, ordering, failure status,
exit codes or coverage collection. The existing runner's `TIMING RESULTS` remains
the source for per-suite/check and aggregate elapsed time. Test-phase times must
not be added to aggregate wall time or combined with parallel suites as if they
were sequential.

## Record provenance in the same execution

Record the exact repository commit (`git rev-parse HEAD`), working-tree status,
command/working directory, Python and pytest versions, platform, flags, exit
status and the full duration section. Keep coverage arguments in the recorded
command. Existing JUnit output may supplement timing, but its per-test `time`
can include multiple phases and must not be labeled a call-only duration.

Treat import/collection/startup time, captured subprocess time, fixture setup,
test-call duration and teardown as different observations. The built-in duration
ranking measures test phases; it does not separately measure Python import or
collection costs, CPU usage, queue delay or CI setup/install time.

## Executed pilot and limitations

One focused execution used unchanged source files from main
`f522f1dd9863c610e3771723274aa9c503889d80`:

- Target: `tests/agent_os_issue_acceptance/test_readiness.py` (43 tests).
- Result: **43 passed in 0.21s**, exit 0, one suite execution.
- Flags: `--durations=20 --durations-min=0`, with an optional local JUnit output.
- Environment: Linux x86_64, Python 3.12.14; pytest 8.4.2 upstream source,
  iniconfig 2.1.0 upstream source, pluggy 1.6.0 upstream source;
  auto-loaded hypothesis plugin 6.98.15 (shown in the captured session header).
- Sample count: one local session; no representative 30-day CI population.
- The top 20 entries were call phases, all displayed as `0.00s`. The first ranked
  node was `test_legacy_build_issue_headings_are_recognized_but_require_tier_decision`.
  This is too short and too small a sample to establish an expensive hotspot.
  Fixture setup did not dominate the displayed ranking; no conclusion about
  fixture costs across the repository is supported.

Direct Git transport and package-index installation were unavailable on the
pilot host. The focused test module, its fixtures, applicable pytest config and
its production imports were materialized at the pinned main revision through
read-only GitHub access. This was a selected-source snapshot, not a complete
checkout or aggregate/exact-head CI run. pytest and its missing dependencies were
materialized separately from pinned upstream tags; their generated version
metadata was supplied locally. No runtime dependency sources or bootstrap files
are added to Agent OS. The test module, fixtures, evaluator modules and pytest configuration retained their fetched content apart from transport-added trailing newlines (no semantic source changes). An empty local package initializer was used to load only the evaluator dependency subset; the repository package initializer and its unrelated export graph were not executed. This means package import/startup behavior was not reproduced. No such initializer change is published to the repository.
The pilot used the same Python test command with only the reporting flags and
an optional JUnit path added, with local import paths supplying those sources.

The host ran other campaign work concurrently. Host load, cache state,
instrumentation and short durations confound comparison. No test
nondeterminism assessment or before/after comparison was performed. Median and
p90 across one session would repeat that single rounded session value, so they
are not presented as population statistics. No speedup or profiling target is
claimed. Independent QA should review the command, source provenance, phase
semantics and limitations rather than treating a green test run as issue-wide
performance evidence.

## Handoff to #520

Carry each future observation with exact SHA/configuration boundaries, actual
sample count, command, versions, raw durations, success/error state and the
phase. Across a comparable series, report median/p90 using a declared percentile
method; classify fewer than 20 sessions as low confidence. Do not confuse a
local focused session with #520's representative recurring-workflow sample.

Use a consistently repeated slow node/phase to nominate a bounded profiling
candidate. Use #1359's suite/aggregate results and native Actions data for
session/job wall time, queue/setup/install/reporting and redundant execution
analysis. Leave optimization and AI Navigation integration to their existing
owners. Rollback of this adoption is deletion of this optional documentation;
no runtime or workflow behavior changes.
