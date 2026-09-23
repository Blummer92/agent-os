# First-publication producer activation (#1428 / #1799 / #1830 / #1978)

`agent_os_execution_service.first_publication_producer` remains the canonical
producer composition. #1799 adds the two-phase #1412 post-validation evidence
envelope, #1830 captures the source phase at the successful authorized-validation
boundary, #1978 adds one minimal pre-validation approval-custody phase under the
same #1412 evidence/store owner, and
`agent_os_execution_service.first_publication_source_activation` supplies the
bounded continuation from one exact durable source capsule to the existing
producer identities. None of these modules is a publisher or Scheduler entrypoint.

## #1412 evidence versions and phases

Legacy schema `1.0` remains checkpoint-bound with unchanged identity semantics.
Schema `1.1` keeps the existing `source` and `checkpoint-bound` phases. Additive
schema `1.2` contains only the new `approval-custody` phase.

A v1.1 `source` capsule carries the exact already-canonical CandidatePacket,
approved ApprovalRecord, RequiredEnvironmentSpec, validation bundle/plan identity,
advisory identities, candidate branch, workspace request, invalidation events,
timestamps, and one bounded non-authorizing execution identity. It has no
checkpoint ID and grants no authority.

A v1.2 `approval-custody` capsule deliberately carries much less: only one exact,
complete, verified `EXECUTION_CANDIDATE` CandidatePacket and the exact approved
`ApprovalRecord` named by that packet's `approval-decision` stage identity, plus
the schema/phase/content identity and hard-false authority fields. It does not
carry RequiredEnvironmentSpec, validation bundle/advisory evidence, invalidation
events, execution authorization, Scheduler execution identity, checkpoint,
ResumePlan, route/dependency evidence, timestamps added only for custody, or a
serialized `SingleIssuePilotInput`.

`bind_source_capsule_to_checkpoint(...)` accepts one exact v1.1 source capsule and
one exact matching #895 checkpoint. Repository, issue, invocation, execution,
branch, source SHA, and tested SHA must all match. Equivalent pairs converge to
the same immutable identity.

The phase-specific loaders are intentionally disjoint:

- `load_approval_custody_pre_publication_evidence(...)` accepts only v1.2
  `approval-custody` evidence;
- `load_source_pre_publication_evidence(...)` accepts only v1.1 `source` evidence;
- publication-facing `load_pre_publication_evidence(...)` accepts only
  checkpoint-bound evidence.

A custody record therefore cannot be mistaken for validation success, source
activation eligibility, or publication eligibility.

## #1978 approval custody

`build_approval_custody_evidence(...)` is the canonical minimal storage contract
for an ApprovalRecord that has already been created by the existing #398/#753
approval pipeline before authorized validation begins. Construction requires the
existing #755 execution-candidate packet to be complete and verified, requires the
ApprovalRecord to be approved, and proves the packet's exact `approval-decision`
identity plus repository/base/candidate/tested/scope/test bindings against that
record. The nested candidate and approval transports continue to verify their own
content identities.

The custody identity stays in the existing public family:

```text
pre-publication-evidence:<64hex>
```

using domain `agent-os-pre-publication-producer-evidence:v1.2\0`. It is stored in
the existing `pre-publication-producer-evidence` namespace under the trusted
checkpoint-store root. Equivalent exact packet + approval evidence converges to
the same identity; no mutable latest pointer, approval index, database, alternate
namespace, or second evidence store is introduced.

Custody is history/evidence, never current authority. A later trusted-host
consumer must independently reacquire current IssuePlan/repository/proposal truth,
run the canonical #398 approval-applicability and #407 projection logic, and
independently reacquire execution authorization before any authorized validation
lifecycle can start. #1970 remains the owner that proves the first-run residual
`invalidation_events=()` only after complete current validation evidence exists.

The post-validation transition does not mutate or promote custody. After a
successful authorized-validation lifecycle, #1830 independently builds the
existing v1.1 `source` capsule. Any future #1972 lifecycle-start composition must
prove the exact approval revision and candidate lineage still match rather than
adding a custody pointer to v1.1 source evidence.

Current production code still has no non-fixture caller that receives the real
human `ApprovalDecision` and invokes this custody builder/store API. #1978 adds the
canonical storage contract only; production human-decision ingestion/capture is a
separate architecture boundary and must not be inferred from GitHub prose, labels,
reviews, execution authorization, or custody presence.

## #1830 source capture

`run_production_authorized_validation_with_source_capture(...)` wraps the existing
#762 authorized-validation lifecycle without changing its admission or execution
semantics. It calls that lifecycle exactly once. Only a terminal `succeeded`
result may proceed to source capture; every other terminal result returns with no
#1412 source write.

The capture reuses existing owners rather than accepting producer evidence from an
external caller:

- CandidatePacket comes from the exact `AuthorizedValidationLifecycleRequest`;
- `SingleIssuePilotInput` is the exact lifecycle input;
- RequiredEnvironmentSpec comes from the already-bound runtime configuration;
- execution identity is the Scheduler-owned deterministic `pilot_holder_identity`
  for the exact `PilotLeaseRequest`, not the #761 evidence-bundle identity;
- `created_at`/`evaluated_at` use the lifecycle's canonical evaluation time;
- expiry is bounded by the execution authorization that admitted the specimen;
- the store root comes only from `load_production_host_configuration()` and its
  existing `ProductionHostConfiguration.checkpoint_store_root`.

The capture then calls `build_source_pre_publication_evidence(...)` once and
`append_pre_publication_evidence(...)` once. It creates no checkpoint, ResumePlan,
route decision, descriptor, handoff, dependency preparation, publication, retry,
or additional Scheduler dispatch. Equivalent source evidence converges through
the existing content-addressed #1412 store.

## #1428 source activation

`activate_first_publication_source(...)` accepts one exact source-capsule identity
plus evidence already reacquired by trusted host composition. It does not accept
store roots, repository paths, workspace paths, commands, credentials, or
authority booleans as part of its request contract. The trusted host supplies the
existing checkpoint-store root outside that bounded request.

The activation checks the source capsule against the current execution identity
before any write, independently requires current execution authorization and
current READY dependency evidence, then composes only existing owners:

```text
exact #1412 source capsule
-> verify repository / issue / invocation / execution / branch / source / tested bindings
-> require current execution authorization
-> require current READY dependency evidence
-> #1431 construct truthful checkpoint from already-observed host evidence
-> #895 append_checkpoint(...)
-> #1799 bind source capsule to exact checkpoint
-> #1412 append checkpoint-bound capsule
-> #895 plan_resume(...) + append_resume_plan(...)
-> #918 select_executor_route(...) + existing route-decision store
-> existing dependency-readiness store
-> return immutable producer identities
-> STOP
```

The activation deliberately does not serialize or persist a complete
`SingleIssuePilotInput`. The irreducible pre-PR evidence comes from the source
capsule; current authorization, dependency, repository/worktree/environment,
acceptance, governance, and route evidence remain host-reacquired inputs owned by
their existing contracts.

## Authority

No custody/source/checkpoint-bound capsule, source capture, or source activation
creates execution authorization. Human approval remains #398/#753-owned; current
approval applicability must be recomputed after custody load. All execution,
publication, Scheduler, GitHub-write, merge, and external-write authority remains
outside these evidence records. Dependency preparation/installation is not
implicit: any non-READY state fails before producer writes.

## Persistence

All three phases use the existing checkpoint-store root and the same
`pre-publication-producer-evidence` namespace. The activation reuses the existing
#895 checkpoint/ResumePlan stores, #918 route-decision store, and #1197 dependency
readiness store. No new root, mutable pointer, approval lookup index, database,
queue, retry store, descriptor store, or alternate persistence owner is
introduced.

## Remaining production boundary

After #1978, the repository has a canonical place to retain an already-created
ApprovalRecord before validation, but a separately governed production operation
must still receive the real human decision and call the custody API. After #1830,
a successful production authorized-validation lifecycle can leave one exact
durable source-capsule identity for #1428. GitHub Actions changes, GCE
deployment/host refresh, live producer execution, #1411 publication, discovery,
resume, replay, and Scheduler execution remain separate authorization boundaries.
