# ChatGPT Orchestrator Routine Coding Context Tests

Issue: #1726

These fixtures verify the bounded routine repository-coding hot context defined by `AGENTS.md`. They do not create a second routing, context, authorization, lifecycle, or execution framework. Existing canonical evaluators remain authoritative.

## Test 1 - Tiny Deterministic Bug Uses Routine Hot Context
Prompt: `Work on #1709`.
Fixture: one open Tier 0/1 `status:ready`, `no-external-write` GitHub issue with one focused adapter-validation objective, resolved ownership, no material blocker, no existing execution conflict, no specialized knowledge requirement, and a fresh direct repository-owner implementation instruction.
Expect: consume canonical request interpretation; acquire live issue/readiness/scope/source-of-truth and existing branch/PR lineage; resolve GitHub Service Agent ownership; apply Safe Implementation Lane/excluded-surface admission; determine the validation obligation for the next transition. Do not preload classroom/PPUX, finite-mission, Terminal Fast Lane, branch-refresh, PR-remediation, checkpoint/ResumePlan, or Scheduler/lease context merely because those mechanisms exist.

## Test 2 - Decision Retrieval Is Lazy
Fixture: Test 1 plus a `CodingKnowledgeRequest` for which CKR10 `plan_decision_preflight(...)` returns `retrieval_required=false`.
Expect: zero Decision Log reads. Continue from canonical GitHub authority. If an explicit Decision/ADR reference or existing CKR10 decision-sensitive signal instead makes retrieval required, load only the existing CKR10 bounded path.

## Test 3 - Lessons Learned Retrieval Is Lazy
Fixture: Test 1 plus a CKR6/CKR11 plan returning `retrieval_required=false` / `not-needed`.
Expect: zero Lessons Learned/Notion reads. Preserve existing failed-PR-repair and CI-diagnosis forced-material-use semantics when those actual repair contexts apply.

## Test 4 - Connector-Native Work Skips Runtime State
Fixture: Test 1 and the exact next action is fully supported by the connected GitHub surface with no checkout, process execution, dependency installation, runtime inspection, Git reconciliation, or resume requirement.
Expect: do not load checkpoint/ResumePlan, Scheduler lease, governed-runner environment, or provider-fallback context. Existing #918 capability semantics still apply if capability evidence becomes material.

## Test 5 - Runtime And Resume Context Activate Only On Trigger
Fixture: the exact next action requires runtime/process capability unavailable on the connected surface, or an existing interrupted execution lineage requires resume.
Expect: activate the existing execution-capability route; load checkpoint/ResumePlan only for genuine resume lineage and Scheduler lease only where governed runtime/concurrency requires it. No new route, state packet, or lease authority is created.

## Test 6 - Branch Refresh And PR Remediation Are Conditional
Fixture A: live PR/base evidence proves the branch is behind/diverged under the existing governed refresh contract.
Expect A: load the branch-refresh path.
Fixture B: current PR/CI/review evidence requires bounded repair or diagnosis.
Expect B: load PR-remediation/diagnostic context.
Negative case: neither condition exists.
Expect: neither context family is part of routine preload.

## Test 7 - Multi-Item And Release Rules Are Conditional
Fixture A: one ordinary issue implementation request.
Expect A: no finite-mission reconciliation context and no Terminal Fast Lane context.
Fixture B: explicit bounded multi-item mission.
Expect B: activate existing finite-mission rules.
Fixture C: canonical request interpretation carries structured `operating-mode=release` for the exact eligible issue.
Expect C: activate existing Terminal Fast Lane composition without inventing authority.

## Test 8 - Classroom And PPUX Context Is Excluded From Routine Coding
Fixture A: Test 1.
Expect A: artifact-first, Teacher Decision Studio, visual-asset-picker, and Picture Perfect / PPUX rules are not part of routine repository-coding preload.
Fixture B: canonical request/context evidence resolves a classroom artifact or existing PPUX tutorial capability.
Expect B: load the existing instructional/domain route normally; the routine coding boundary does not remove those capabilities.

## Test 9 - Immutable Evidence Reuse Does Not Become Stale Caching
Fixture: one same-lineage implementation where repository identity, issue identity, objective, bounded scope, and canonical owner are unchanged while PR head/validation/review state advances.
Expect: reuse unchanged immutable facts; reacquire mutable evidence required by its canonical freshness contract, including current issue state/authorization applicability, PR/head/base, validation, reviews, and active execution/lease state. Do not create a new Task State Capsule, cache, or context manager.

## Test 10 - Safety Invariants Survive Context Reduction
Fixture: routine context reduction encounters ambiguous source of truth, stale authorization, excluded surface, material architecture/schema/ownership change, stale exact-head validation, or active/ambiguous execution conflict.
Expect: fail closed through the existing canonical owner. Reduced preload never suppresses source-of-truth, authorization, ownership, excluded-surface, exact-head validation, concurrency, or audit requirements.
