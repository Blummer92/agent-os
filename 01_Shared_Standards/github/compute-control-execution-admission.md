# Compute-Control Execution Admission

## Invariant
Every governed execution-admission or continuation seam that can spend runtime, validation, model, runner, VM, or external-tool compute must consume the canonical #1419 compute-control projection before that compute is spent.

This standard does not define a second compute router, readiness engine, validation selector, Scheduler, execution authority, or evidence model.

## Disposition handling
Consume the existing canonical disposition unchanged:

- `do-not-spend-compute-yet` / `unavailable`: stop before expensive execution and surface the canonical reason;
- `reuse-existing-evidence`: suppress new validation only when existing exact-identity applicability rules prove reuse;
- `focused-validation-first`: use only the existing focused-validation path;
- `final-cloud-validation-required`: preserve the existing exact-head final-validation path;
- `duplicate-or-obsolete-run-risk`: reconcile through existing currentness/Scheduler owners or fail closed; never blindly start a competing run;
- `run-now`: continue through existing authorization and capability routing. This disposition creates no authority.

## Admission order

```text
candidate work
-> canonical bounded evidence
-> canonical #1419 compute-control projection
-> admitted disposition
-> existing execution/capability route
```

Do not invoke a governed runner, VM, Cloud Build, model/tool execution, or dependency setup merely to discover a blocker already represented by canonical deterministic evidence.

## Fail closed
Missing, stale, malformed, conflicting, ambiguous, or incomplete compute-control evidence blocks expensive execution. Notion or working-layer state cannot grant admission.

## Validation separation
Focused developer validation and final exact-head validation remain separate canonical stages. Compute admission may select the correct existing stage but cannot mark either stage complete.

## Continuation
Same-lineage continuation must reacquire current evidence before re-admission. Old-head evidence cannot suppress current-head validation. Duplicate/obsolete active execution risk cannot start a second run by default.

## Authority
This projection grants no implementation, merge, closure, production, protected-setting, credential, workflow, or external-write authority. Existing authorization and execution owners remain authoritative.
