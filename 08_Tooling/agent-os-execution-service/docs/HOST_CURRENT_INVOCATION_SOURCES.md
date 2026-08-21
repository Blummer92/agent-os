# Host Current Invocation Sources

## Purpose

Issue #1253 established the repository-owned host composition behind the existing `InvocationEvidenceSources` contract. Issue #1303 closes the remaining production source gap without changing that authority model.

`HostCurrentInvocationSources` still performs descriptor-binding rejection only. `CanonicalCurrentInvocationResolver` remains responsible for exact current evidence construction and execution-authorization reacquisition; `reconstruct_governed_invocation(...)` remains responsible for full cross-binding/currentness checks and existing Scheduler lease observation.

No component here creates Scheduler, lease, retry, authorization, merge, or execution authority.

## Canonical order

```text
executor-handoff:<sha256>
-> GovernedInvocationDescriptor loader
-> ProductionHostStateSources
   -> #1304 route decision reader
   -> #1304 full handoff reader
   -> #895 exact checkpoint reader
   -> #1304 ResumePlan reader
   -> bounded restart capsule (static, non-authorizing evidence only)
   -> fresh #750-#755 candidate-stage reacquisition
   -> fresh approval applicability + approved projection
   -> fresh validation-plan selection
   -> runtime configuration rebuilt from host-controlled configuration
   -> validation/advisory evidence deterministically rebuilt
   -> in-memory SingleIssuePilotInput
-> HostCurrentInvocationSources binding checks
-> CanonicalCurrentInvocationResolver
   -> fresh execution-authorization reacquisition (#1226/#1227)
-> reconstruct_governed_invocation(...)
   -> #1218/#1253 binding/currentness checks
   -> #758/#1202 lease observation
-> admitted current SingleIssuePilotInput or fail closed
```

## The bounded restart capsule

`governed_resume_restart_capsule.py` is the single static continuation artifact permitted by #1303's consolidation decision. It is keyed by the existing immutable handoff identity and lives under the existing checkpoint-store root using the same bounded atomic-write and symlink-safety primitives already reused by #1304.

The capsule carries only evidence that cannot be recovered from the small descriptor alone: the immutable CandidatePacket, the immutable approval decision record, the immutable `RequiredEnvironmentSpec` (#1320), canonical validation observations, expected validation/advisory identities, candidate branch/workspace identity, and bounded invalidation/timing evidence. Every authority flag is fixed `False`.

The capsule does **not** persist a `SingleIssuePilotInput`, current authorization, Scheduler lease/admission state, current issue state, current repository state, current proposal, or current projection. Stored presence never grants currentness or execution authority.

Publication is fail-closed: `publish_governed_handoff(...)` persists the capsule after #1304's route/handoff/checkpoint/ResumePlan durability checks and before the descriptor becomes discoverable. A capsule write failure therefore cannot expose a runnable descriptor whose static restart evidence is missing.

The capsule step extends the existing #1243/#1304 publication seam rather than adding a second publication path. Capsule construction stays inside the seam's existing current-evidence boundary, so unbuildable restart evidence fails closed as `current-evidence-malformed` before any artifact is persisted. Capsule persistence adds exactly two bounded reason codes, `restart-capsule-persistence-failed` and `restart-capsule-persistence-mismatch`; both block descriptor persistence and neither retries. `tests/test_handoff_publication.py` owns this ordering and fail-closed contract for every step in the seam.

## Required-environment persistence and recovery (#1320)

AOS-GCE2F (#1320) added the `RequiredEnvironmentSpec` slot through this one existing capsule and its existing atomic/path-safe store. No new store, database, service, registry, cache, daemon, or persistence directory was created, and the capsule schema version moved to `1.1` so an older payload fails closed rather than being reinterpreted.

`publish_governed_handoff(...)` persists the exact specification already bound into the verified `ConcreteRuntimeConfiguration`; a configuration with no bound specification fails closed as `current-evidence-malformed` before any artifact is written. `build_restart_capsule(...)` additionally re-checks that the specification's `required_validation_command_ids` bind to the CandidatePacket's required tests, reusing the same canonical rule the runtime configuration and validation stage already enforce.

Recovery is `build_required_environment_spec_reader(store_root)`, the `RequiredEnvironmentSpecReader` #1303 expects and #1319 can compose without learning any source-of-truth internals. It loads the capsule for the descriptor's exact handoff identity, rebuilds the specification through the one canonical `reconstruct_required_environment_spec(...)` transport in `scripts.agent_os_execution_capabilities.dependencies`, and fails closed when the payload is missing, malformed, field-drifted, content-mismatched, or asserts an identity other than the descriptor's `required_environment_id`. #1303 keeps its own descriptor identity gate; the reader adds no second one.

The persisted specification is **declarative requirement data only**. It never proves that dependencies are installed or READY. #1185/#1197 `DependencyReadinessEvidence` remains the sole runtime dependency-readiness authority and is reacquired and currentness-checked independently, exactly as described under "Dependency-readiness recovery" below. Validation plans and evidence remain owned by the existing validation contracts; no GitHub check or CI status becomes canonical validation evidence.

## Current evidence reacquisition

`ProductionHostStateSources` implements all seven production slots as one bounded composition rather than seven independent mini-systems.

The four immutable readers call the existing #1304/#895 stores directly. The candidate path then uses the existing `prepare_candidate_packet(...)` stages with caller-supplied read-only source transports and a current `RepositoryObservation`; it does not parse issue prose or invent repository state itself.

The stored approval decision is re-evaluated with canonical `evaluate_approval_applicability(...)` against the freshly reacquired proposal, IssuePlan evidence, and repository evidence. `build_approved_execution_projection(...)` then rebuilds the current projection. Exact CandidatePacket stage identities are compared against those fresh objects, so a historical packet is returned only when its bound source/IssuePlan/planning/repository/proposal/approval/projection identities remain current.

## Validation and runtime reconstruction

The complete Scheduler validation plan is selected again through the canonical remote-validation selector from the current candidate changed-path set. Its semantic ID must equal the capsule's expected validation-plan ID.

The validation bundle is rebuilt from the capsule's bounded command observations plus the freshly accepted governed projection and current validation plan. The advisory result and render are then regenerated with their canonical builders. Their IDs must exactly match the capsule. No stored validation object is treated as current merely because it exists.

`ConcreteRuntimeConfiguration.bind_candidate(...)` rebuilds runtime configuration from the current projection/validation IDs plus host-controlled repository root, workspace parent, lease directory, optional delegated cgroup, and required-environment specification. The resulting fingerprint must match the descriptor. Remote argv cannot supply these host-controlled values.

Only after these checks does `ProductionHostStateSources.pilot_input(...)` assemble a `SingleIssuePilotInput` in memory. The existing runtime configuration verifies that exact pilot input before it can reach #1218 admission.

## Dependency-readiness recovery

Merged PR #1254 made bounded, content-addressed `DependencyReadinessEvidence` restart-recoverable in the checkpoint-owned append-only store. `HostCurrentInvocationSources` continues to load it by the descriptor-bound evidence identity and verify source SHA, required-environment identity, environment-health identity, execution surface, and workspace identity.

Persistence does not establish currentness. Existing #1218 checks still require READY evidence in its valid time window. Matching SHA alone is insufficient when workspace, environment, or execution-surface identity differs.

## Host-controlled read adapters

The production source layer accepts the already-defined `IssueSourceReader` / `RepositoryEvidenceReader` contracts, a read-only current `RepositoryObservation` provider, an optional dependency-identity reader, and a required-environment-spec reader. Those are transport/configuration boundaries only; the canonical parsing, planning, applicability, projection, validation, runtime, currentness, authorization, and admission semantics remain in their existing owners.

A host must not replace these adapters with issue-prose inference, descriptor snapshots, arbitrary shell output, remote argv, or hidden VM-only state-discovery rules.

## Fail-closed behavior

Missing, malformed, ambiguous, stale, or identity-mismatched capsule/current evidence raises `CurrentInvocationResolutionError`; the existing resolver maps unavailable current evidence to a non-admitted result. Descriptor presence alone remains insufficient.

The current source composition verifies repository/issue/invocation/source bindings, CandidatePacket stage identities, current approval applicability, projection identity, candidate-bound validation subject, Scheduler validation-plan identity, runtime fingerprint, and validation/advisory identities before returning the in-memory pilot input.

## Authority boundary

Successful composition authorizes no side effect. It does not dispatch the Scheduler; acquire/release/recover a lease; create execution authorization; write GitHub; mutate cloud/IAM/VM/IAP/OS Login; change workflows/protected settings; retry/fallback; persist a complete `SingleIssuePilotInput`; merge; or close an issue.

Workflow Scheduler remains the sole admission/lease/execution authority. #1218/#1253 remain the reconstruction/currentness authority.

## #1287 handoff

#1287 can now consume `ProductionHostStateSources` rather than inventing deployment-local state-discovery semantics. Its installed entrypoint composition should construct one source object from the approved host read transports/configuration and pass these bound methods to `build_production_governed_resume_bindings(...)`:

1. `route_decision`;
2. `handoff`;
3. `checkpoint`;
4. `resume_plan`;
5. `candidate_packet`;
6. `runtime_configuration`; and
7. `pilot_input`.

#1287 still owns installed-entrypoint wiring. #1238 remains downstream host verification, and #1239 remains live qualification.

## Rollback

Revert the #1303 production source module, restart-capsule module/tests, publication hook, the #1320 required-environment capsule slot/reader and its canonical spec-reconstruction helper, and this documentation. Existing #1218/#1253 reconstruction/currentness, #1304 durable route/handoff/checkpoint/ResumePlan records, Scheduler leases, and external resources remain unchanged.
