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


## Governed Test-Campaign Reconciliation

Before recommending another manual, conversational, benchmark, or adversarial test in an active governed campaign, reacquire the canonical campaign owner and its current result evidence. Reconstruct only the smallest evidence-backed completed-test matrix needed for the next-test decision; do not create a second test-state store, experiment database, conversation-memory system, or parallel source of truth.

Compare proposed conditions semantically against that matrix rather than by prompt text alone. Classify every candidate as exactly one of:

- `new condition` — the material behavior/configuration condition is not already evidenced;
- `intentional repeat` — materially equivalent work is rerun for a stated measurement purpose such as regression verification, changed model/configuration, variance, or changed dependency;
- `already completed` — current canonical evidence already answers the proposed condition.

Recommend `new condition` candidates by default. An `intentional repeat` must state what changed or what measurement the repetition provides before it is recommended. Never present an `already completed` condition as new work. When the planned matrix is sufficiently populated, recommend synthesis, decision, or the genuinely unresolved acceptance condition instead of inventing more tests.

For conversational/manual tests, any selected `new condition` or `intentional repeat` must carry the active campaign's reproducibility metadata contract: exact prompt, model/configuration, user-visible reasoning/thinking setting, same-chat or fresh-chat mode, required prior turns/context, required attached/project sources, expected behavior/pass criteria, failure signals, result-evidence location, and timestamp/config notes when material. Existing campaign evidence remains canonical at its owning issue; bounded protocol/index cross-references may point to it without duplicating full test bodies.

## Authoritative Final Validation

- The full suite remains required before release or Ready-for-Review when the governing repository workflow requires aggregate validation.
- One clean aggregate run bound to the exact final pull-request head may satisfy the full-suite requirement, including when that run is performed by GitHub CI.
- CI evidence from any SHA other than the current required head is stale for that head and cannot satisfy the transition.
- A focused pass never suppresses, replaces, or impersonates the required final exact-head aggregate.
- Ordinary Ready-for-Review, release, or any later transition that consumes required validation must wait for the required exact-head evidence even when Draft PR creation was allowed to stage CI-routed validation.
- When the repository's existing Ready event is itself the only currently capable governed trigger for the required exact-head aggregate, one reversible **provisional Ready** transition may be used solely to stage that aggregate after exact-head currentness, review convergence, focused validation, and Ready authority are proven. Provisional Ready grants no merge or later lifecycle authority. The exact-head aggregate must then succeed before Ready is treated as converged; failure, cancellation, missing evidence, or head drift requires conversion back to Draft before further progression.
- Release only with required exact-head evidence and checklist status.

## Version
0.6.0

## Changelog
- 0.6.0 adds #2872 governed test-campaign reconciliation before next-test recommendations: reacquire canonical campaign evidence, semantically classify candidates as `new condition`, `intentional repeat`, or `already completed`, require a stated purpose for repeats, and preserve the conversational/manual reproducibility metadata contract without adding a second test-state store.
- 0.5.0 adds #2852's reversible provisional-Ready validation trigger for the existing Ready-event aggregate path when no other capable governed aggregate trigger is available; exact-head success is still required before Ready converges and any non-success requires Draft rollback. No merge, closure, workflow-edit, permission, production, or external-write authority is added.
- 0.4.1 rewords the exact-head governed CI aggregate sentence in Developer Loop Validation so its subsuming-evidence phrase is contiguous and test-verifiable, with no change in meaning (#1594).
- 0.4.0 separates validation obligation from execution location, permits Draft PR staging when an existing governed CI executor is the capable route, forbids false manual-command stops, and preserves exact-head evidence before Ready-for-Review or release (#1595).
- 0.3.0 makes issue-required developer-loop checks a pre-PR capable-route gate while preserving one authoritative exact-head aggregate.
- 0.2.0 separates focused developer-loop validation from one authoritative exact-head full aggregate, avoiding mandatory duplicate local aggregate execution while preserving final coverage.
- 0.1.0 initial testing and release baseline.