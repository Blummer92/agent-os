# Production handoff publication activation (#1411)

`agent_os_execution_service.production_handoff_publication` is the fixed production-host activation path for first governed handoff publication.

## Bounded caller contract

The module entrypoint accepts exactly three content-addressed identities:

- `--capsule-id pre-publication-evidence:<64hex>`;
- `--route-decision-id executor-route-decision:<64hex>`;
- `--dependency-readiness-id dependency-readiness:<64hex>`.

It accepts no store root, repository path, workspace path, lease path, Python path, command, credential, host, retry, fallback, or Scheduler argument. Static host locations come only from the existing `ProductionHostConfiguration` environment contract.

## Evidence ownership

The entrypoint loads the #1412 producer-evidence capsule from the canonical checkpoint store. The capsule is evidence only and all of its authority fields remain false. It independently:

1. loads the exact durable checkpoint bound by the capsule;
2. loads the exact ResumePlan bound by the existing #918 route decision;
3. loads current dependency-readiness evidence;
4. reacquires current owner-authored execution authorization through the existing GitHub read-only authorization source;
5. reacquires current issue/repository evidence and replays the existing candidate/approval/validation/runtime composition;
6. rebuilds the complete `SingleIssuePilotInput` in memory only;
7. delegates exactly once to #1409 `publish_authorized_validation_handoff(...)`.

#1409 remains the caller-facing admission boundary and #1243 remains the sole handoff/descriptor publication ordering and persistence owner. This module does not call `publish_governed_handoff(...)` directly.

## Fixed #918 handoff profile

The caller-owned #918 handoff tuples are fixed by this production composition and are not argv-selectable:

- required return evidence: `exact-head-sha`, `test-results`;
- stop conditions: `excluded-surface-entered`, `scope-expanded`.

These values are bounded handoff metadata only; they create no execution, publication, merge, or external-write authority.

## Fail-closed behavior

Missing, malformed, stale, unavailable, or conflicting capsule/checkpoint/ResumePlan/route/dependency/authorization/repository/runtime evidence prevents the #1409 call. No substitute path, default store, synthesized handoff, automatic re-attempt, fallback route, Scheduler dispatch, or lease consumption is performed by #1411.

## Live activation boundary

Repository implementation does not install or invoke this module on the production host. Host installation/deployment and a live publication attempt remain separately authorized. A successful publication still grants no permission to run `/agent-os discover`, `/agent-os resume`, replay, or Scheduler execution unless those steps are separately admitted.
