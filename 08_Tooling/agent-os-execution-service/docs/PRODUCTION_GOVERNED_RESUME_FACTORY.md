# Production Governed Resume Factory

Issue #1217 connects the installed #1238 governed-resume entrypoint to the repository-owned production composition delivered by #1319 without adding a second Scheduler, currentness engine, evidence model, checkpoint store, lease system, retry system, router, or execution authority.

## Fixed entrypoint path

The installed wrapper remains:

```text
/usr/local/libexec/agent-os-governed-resume \
  --handoff-id executor-handoff:<64-lowercase-hex>
```

`governed_resume_entrypoint.main()` validates this immutable argv contract before any production host factory is imported or invoked. Explicitly injected `GovernedResumeBindings` remain supported for tests and governed callers. `_no_host_composition_bindings` remains the explicit fail-closed no-host-composition path.

## Default production composition

With no injected bindings, the entrypoint calls `build_production_governed_resume_bindings_for_handoff(...)`. The factory performs only the minimum evidence reacquisition needed to construct the existing #1319 bootstrap:

1. load host configuration from the existing #1319 environment-owned configuration boundary;
2. load the immutable invocation descriptor and #1303/#1320 restart capsule for the exact handoff;
3. verify descriptor, candidate-packet, required-environment, repository, issue, invocation, and source-SHA bindings;
4. load the canonical #1185/#1197 `DependencyReadinessEvidence` by the descriptor's exact content identity;
5. rebuild the existing advisory validation result from the capsule's canonical validation bundle and require the recomputed advisory identity to match the capsule;
6. construct #1320 `LiveRepositoryEvidenceReader` for that exact subject;
7. construct the existing #1319 read-only GitHub transport and canonical verifier runner;
8. pass those inputs to `build_production_host_bootstrap(...)`;
9. obtain the existing #1287 production `GovernedResumeBindings` and return them to the unchanged `run_governed_resume(...)` path.

The factory does not infer dependency readiness from `RequiredEnvironmentSpec`, issue prose, labels, PR state, generic CI state, or descriptor presence. The specification remains declarative; current runtime readiness comes only from the canonical persisted dependency-readiness evidence.

## Validation evidence

The restart capsule already persists the canonical validation bundle, validation-plan identity, and advisory-result identity. The factory reconstructs the existing `ValidationPlan` and `SuppliedCommandResult` values from that bundle, invokes the existing `evaluate_advisory_pre_pr_evidence(...)` function, and requires the rebuilt result identity to equal the capsule's `advisory_result_id`.

This is reconstruction of an existing canonical artifact, not a new validation store or status model. Missing, malformed, mismatched, or stale data fails closed before Scheduler dispatch.

## Fail-closed behavior

Production factory errors are surfaced through the entrypoint's existing host-composition failure boundary. Malformed argv is rejected before production composition. Missing host configuration, descriptor/capsule drift, missing dependency-readiness evidence, malformed validation evidence, missing GitHub read credentials, unavailable read sources, currentness failures, or bootstrap/composition failures result in no Scheduler dispatch.

The existing #1218/#1253 reconstruction path still reacquires current issue, authorization, repository, checkpoint/ResumePlan, environment, and lease evidence. The existing Workflow Scheduler remains the only dispatch/admission lifecycle owner.

## Known repository-ref vocabulary gap

The pre-existing `origin/main` versus `main` verifier/repository-stage vocabulary mismatch is not changed by #1217. #1319 already records it as a cross-contract gap owned by the canonical verifier/repository-stage contracts. This repository-only entrypoint wiring does not normalize refs locally because doing so here would make the bootstrap a second owner of repository-state semantics. Live qualification must keep failing closed until that owning contract is reconciled.

## Authorization boundary

This repository-only slice performs no `.github/workflows/**` changes, IAM/WIF/service-account changes, credential or secret changes, VM mutation, IAP/SSH, deployment, production activation, protected-setting changes, merge, auto-merge, issue closure, or live external execution.

## Rollback

Revert `production_governed_resume_factory.py`, the #1217 entrypoint selection change, directly corresponding tests, and this document. Preserve #1238's fixed installed wrapper, #1319 bootstrap/read transport, #1320 evidence semantics, #1303 state sources, #1287 production composition, #1218/#1253 reconstruction/currentness, Scheduler leases, checkpoint history, and all external resources.
