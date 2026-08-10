# Testing And Release

## Developer Loop Validation

- After a change, run the smallest relevant focused tests that cover the changed or directly affected behavior.
- A focused pass is non-final evidence: treat it as `aggregate-pending`, not as final validation success.
- Do not run another local full aggregate solely before pushing when a clean exact-head CI aggregate will run the full suite.
- Expand local testing when focused tests fail, when exact-head CI reports a specific failure that needs diagnosis, when CI is unavailable, or when the governing issue explicitly requires broader local validation.

## Authoritative Final Validation

- The full suite remains required before release or Ready-for-Review when the governing repository workflow requires aggregate validation.
- One clean aggregate run bound to the exact final pull-request head may satisfy the full-suite requirement, including when that run is performed by GitHub CI.
- A focused pass never suppresses, replaces, or impersonates the required final exact-head aggregate.
- Release only with required exact-head evidence and checklist status.

## Version
0.2.0

## Changelog
- 0.2.0 separates focused developer-loop validation from one authoritative exact-head full aggregate, avoiding mandatory duplicate local aggregate execution while preserving final coverage.
- 0.1.0 initial testing and release baseline.
