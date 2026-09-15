# Release-run lifecycle closure admission

Issue: #2149

`agent-os-release-run.py` must not treat a caller-supplied `issue_closure_authorized` boolean as closure authority. Ordinary Safe Implementation Lane work remains non-authorizing for issue closure.

The release evaluator consumes `issue_closure_lifecycle` containing exactly the canonical `LifecycleMutationAuthorization` and the exact `LifecycleStateSnapshot` used for admission. It reconstructs those existing content-bound records, verifies that the snapshot matches the release repository, issue, pull request, observed head, and issue state, then calls the existing `evaluate_lifecycle_mutation(..., "close-issue")` owner.

Only an `ADMITTED` result projects `issue_closure_authorized=True` into the existing release state machine. Missing evidence, a legacy raw boolean, wrong target, stale head/state, non-authorized/consumed/superseded authorization, or any canonical lifecycle admission failure leaves closure unauthorized and routes to the existing issue-closure authorization pause.

The implementation does not perform GitHub writes, close issues, infer owner intent, create a second lifecycle engine, or weaken merge/closure separation. The actual close mutation and canonical readback remain owned by the existing GitHub lifecycle executor path.
