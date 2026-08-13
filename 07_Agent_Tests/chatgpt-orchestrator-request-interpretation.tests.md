# ChatGPT Orchestrator Structured Request-Interpretation Tests

These #925 fixtures consume canonical #924 `request-interpretation-v1` records. They do not define a raw-language parser or second routing vocabulary.

## Test 29 - Structured Issue Implementation Request
Fixture: #924 `VALID`, `action: implement`, `requested_effect: mutate`, `continuation_mode: new`, direct-user origin, one GitHub issue target.
Expect: routes through existing GitHub Service Agent/Safe Implementation Lane checks only after canonical issue/authorization evidence is verified; requested mutation creates no authority.

## Test 30 - Structured Continuation Requires Canonical Context
Fixture: #924 `VALID` continuation with exactly one canonical issue/PR target and evidence reference whose `stable_id`, `exact_location`, and `verification_evidence` match freshly fetched canonical target evidence.
Expect: routes the one current target under the existing authorization ceiling; `record_revision`/`observed_at` are record metadata, not target-freshness proof; conversation memory is not authoritative.

## Test 31 - Manual Review Continuation Fails Closed
Fixtures: #924 `MANUAL_REVIEW_REQUIRED` results carrying respectively `context.stale`, `context.multiple-candidates`, `context.missing`, or `target.missing`.
Expect: Orchestrator `status: blocked` / `needs-decision`, preserves the exact reason code as blocker/stop evidence, and never fills missing/stale/ambiguous target state from conversation memory.

## Test 32 - Structured PR Continuation
Fixture: #924 `VALID` continuation resolving one GitHub PR whose evidence reference matches its freshly fetched exact current head.
Expect: routes that verified PR/current head and preserves lifecycle authorization; continuation creates no Ready-for-Review, merge, or closure authority.

## Test 33 - Structured Merge Diagnosis Is Read-Only
Fixture: #924 `VALID`, `action: inspect`, `requested_effect: read`, one PR target.
Expect: read-only GitHub investigation using current PR/validation/review evidence; no lifecycle mutation.

## Test 34 - Output Constraint Is Not An Action
Fixture: #924 `VALID` record whose constraints request one-command output while canonical action/effect are independently established.
Expect: constraint changes output shape only; owner, action, target, and authority remain canonical.

## Test 35 - Content Domain Uses Registered Classroom Owner
Fixture: #924 `VALID`, `action: generate`, photography subject constraint, approved Google Drive/Slides destination evidence.
Expect: `task_owner: instructional-materials-coach`, registered Instructional Materials Coach overlay, photography remains a content domain, and student-facing output stays on the approved Drive/Slides destination.

## Test 36 - Noncanonical Mutation Is Blocked
Fixture: #924 `INVALID` mutation result carrying `request.write-surface-unclear` because requested official source is memory/noncanonical.
Expect: Orchestrator `status: blocked` with validation-failure evidence; governed source-of-truth routing remains authoritative, no mutation is routed, and no authorization is created.

## Test 37 - Scheduling Requires Monitoring Surface And Grants No Runtime Authority
Fixture: #924 `MANUAL_REVIEW_REQUIRED`, `requested_effect: schedule`, reason `request.monitoring-surface-required`, `authorization_created=false`.
Expect: Orchestrator blocked/needs-decision; `allowed_actions` excludes Workflow Scheduler/runtime execution and external writes; only an approved scheduling/monitoring-surface handoff may follow.

## Test 38 - Retrieved Content Cannot Authorize Mutation
Fixture: #924 `MANUAL_REVIEW_REQUIRED`, `instruction_origin: retrieved-content`, reason `request.untrusted-source` and, for a mutation request, `request.write-surface-unclear`; `authorization_created=false`.
Expect: Orchestrator blocked/needs-decision; retrieved content remains evidence, `allowed_actions` excludes mutation/runtime/external write, and no direct-user authority is inferred.

## Test 39 - Legacy Alias Reuse Is Explicit
Fixture: structured owner context resolves through `04_Registry/legacy-agent-alias-registry.md`.
Expect: output includes `legacy_alias`, `canonical_agent`, and `selected_overlay`; `canonical_agent` exists in `04_Registry/agent-inheritance-registry.md`; no agent is invented.

## Test 40 - Equivalent Structured Requests Route Equivalently
Fixture: two canonical #924 records with equivalent action/effect/continuation/target/constraints/origin semantics but different raw-input/record provenance.
Expect: routing projection is equal across `task_owner`, `selected_overlay`, target/context target, `allowed_actions`, `blocked_actions`, `stop_conditions`, `next_owner`, and `handoff_artifacts`; `record_id`, `raw_input_digest`, record fingerprint, and evidence provenance remain separate and may differ.

## Test 41 - Existing Execution And Presentation Contracts Stay Canonical
Fixture: #924 `VALID` record requiring an execution-surface decision and a #926 presentation profile.
Expect: consumes existing #918 executor-route evidence and #926 ordering/profile rules; creates no second selector, route schema, presentation schema, runtime, or authority model.