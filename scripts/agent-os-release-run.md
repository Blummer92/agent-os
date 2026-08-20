# Agent OS Release Run

`agent-os-release-run.py` is the deterministic offline state evaluator for the governed release lifecycle. It performs no GitHub, Scheduler, credential, production, or external-system mutation.

## Canonical inputs

Callers supply fresh evidence for repository/issue/PR identity, exact head and current `main`, branch freshness, bounded changed-file scope, canonical required checks, authoritative exact-head validation, review state, current lifecycle reconciliation, authorization projections, and any applicable #1187 branch-refresh receipt.

The evaluator composes existing owners rather than replacing them:

- `IssueOperationalState` / `operating_mode.py` own lifecycle authorization ceilings;
- #988 owns failure attribution;
- #1038 owns managed PR lifecycle/projection reconciliation;
- #1187 owns base-behind branch refresh and head-bound invalidation;
- checkpoint/ResumePlan evidence owns lineage terminalization;
- Scheduler lease/fencing owns exact lease disposition and release.

Managed labels are derived projections only. They never grant Ready-for-Review, merge, closure, refresh, or any other authority.

## Reacquisition and validation

Reacquire live PR/head/base/lifecycle/review/check evidence at every phase boundary. Checkpoint values are comparison evidence, never authority. Unexpected head movement, stale exact-head validation, conflict/unknown freshness, unresolved blocking review, missing canonical checks, or ambiguous external transition fails closed.

A behind branch routes only through #1187. After refresh, only the refreshed exact head may satisfy terminal validation, and the required head-bound evidence must be invalidated/recomputed according to the existing refresh contract.

## Ready-for-Review, merge, and closure

`ready_for_review_authorized`, `merge_authorized`, and `issue_closure_authorized` are independent caller-supplied authority projections. The evaluator never infers any of them from green CI, labels, continuation language, or requested mode.

Ordinary Safe Implementation Lane normally reaches Ready-for-Review and then stops because merge/closure authority is absent. For an eligible Terminal Fast Lane request, the same canonical release evaluator is reused; the prior validated `request-interpretation-v1` plus current `IssueOperationalState` / `operating_mode.py` path may cause the caller to supply current merge/closure authorization projections without another user prompt. The evaluator still applies every existing exact-head, review, merge-method, lifecycle, and closure gate.

## Terminal reconciliation

After a governed merge is verified, terminal progression is ordered and idempotent:

1. publish the concise completion pointer;
2. terminalize/supersede the current checkpoint/ResumePlan lineage through its owner;
3. prove terminal lease disposition and, when required, consume an exact non-forced, unambiguous release receipt matching lease identity, holder, and generation;
4. close the implementation issue only when closure authorization is current;
5. require converged `final-state-readback` lifecycle reconciliation bound to the exact head;
6. emit one final report;
7. converge to `COMPLETED`.

The release-run module owns ordering only. It does not reimplement checkpoint, lease, GitHub mutation, label reconciliation, or authorization semantics.

## Safety

Terminal Fast Lane is not available to Tier 2, protected-setting/workflow, credential/IAM, production, external-write, source-of-truth, irreversible, or otherwise excluded work. Auto-merge, review dismissal, branch deletion, merge queue/bypass, workflow reruns, protected-setting changes, and lease stealing/force-release remain outside this evaluator.
