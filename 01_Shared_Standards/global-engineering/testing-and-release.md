# Testing And Release

## Developer Loop Validation

- After a change, run the smallest relevant focused tests that cover the changed or directly affected behavior when a capable authorized developer-loop executor is available.
- Validation obligation and validation execution location are separate decisions. A required check must pass before the lifecycle transition that consumes it, but it is not inherently a local/manual or pre-Draft-PR command.
- Issue-required focused, structural, compile or lint, line-count, and diff checks designated for the developer loop should run on the cheapest capable authorized executor. Prefer the active/local execution surface when it can run them safely; otherwise reuse the canonical executor-routing contract.
- When the active execution surface cannot run a required developer-loop check and the repository already provides a governed CI route capable of producing the required evidence, Draft PR creation may stage that CI-routed validation. Do not stop or require user copy/paste shell commands solely because the active connector lacks runtime capability.
- A Draft PR may therefore exist while CI-routed developer-loop evidence is pending when that staging is required to invoke or bind the governed CI executor. The pending state grants no Ready-for-Review, merge, closure, production, credential, permission, or external-write authority.
- If neither the active execution surface, the canonical governed runner, nor an existing governed CI route can produce the required evidence, stop with `needs-decision`.
- A focused pass is non-final evidence: treat it as `aggregate-pending`, not as final validation success. When focused checks are subsumed by one, an exact-head governed CI aggregate may provide both the required focused behavior evidence and the authoritative final aggregate evidence; do not require duplicate local execution solely to satisfy location.
- Do not run another local full aggregate solely before pushing when a clean exact-head CI aggregate will run the full suite.
- Expand local testing when focused tests fail, when exact-head CI reports a specific failure that needs diagnosis, when CI is unavailable, or when the governing issue explicitly requires broader local validation.

## Authoritative Final Validation

- The full suite remains required before release or Ready-for-Review when the governing repository workflow requires aggregate validation.
- One clean aggregate run bound to the exact final pull-request head may satisfy the full-suite requirement, including when that run is performed by GitHub CI.
- CI evidence from any SHA other than the current required head is stale for that head and cannot satisfy the transition.
- A focused pass never suppresses, replaces, or impersonates the required final exact-head aggregate.
- Ready-for-Review, release, or any later transition that consumes required validation must wait for the required exact-head evidence even when Draft PR creation was allowed to stage CI-routed validation.
- Release only with required exact-head evidence and checklist status.

## Version
0.4.1

## Changelog
- 0.4.1 rewords the exact-head governed CI aggregate sentence in Developer Loop Validation so its subsuming-evidence phrase is contiguous and test-verifiable, with no change in meaning (#1594).
- 0.4.0 separates validation obligation from execution location, permits Draft PR staging when an existing governed CI executor is the capable route, forbids false manual-command stops, and preserves exact-head evidence before Ready-for-Review or release (#1595).
- 0.3.0 makes issue-required developer-loop checks a pre-PR capable-route gate while preserving one authoritative exact-head aggregate.
- 0.2.0 separates focused developer-loop validation from one authoritative exact-head full aggregate, avoiding mandatory duplicate local aggregate execution while preserving final coverage.
- 0.1.0 initial testing and release baseline.