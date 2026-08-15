# Module Version Map — Details

Extended module descriptions moved out of `module-version-map.md` to keep that
index below 100 lines. See that file for the canonical version table.

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) is `0.15.0` under
AOS-RUNNER1D (#1185). The existing single-issue runtime now owns one optional,
task-scoped dependency-readiness gate after verified workspace inspection and
before executor or validation dispatch. It consumes the existing GEX
`RequiredEnvironmentSpec` / `DependencyReadinessEvidence` domain and upstream
#972 execution-surface health identity; it does not create a second runner,
Scheduler, candidate packet, environment-health schema, package manager, retry
service, cache service, or provider-specific provisioning path. Python/pip uses
one bounded requirements/local-project/qualification-pin preparation attempt;
Node/npm requires `npm ci` for a committed lock, allows `npm ci --offline` only
with proven complete compatible cache evidence, and treats explicitly authorized
lock generation as `source-update-required` until the new lock is committed and
the packet is rebound to the new exact head. Provider and validation dispatch
fail closed without current READY evidence, and dependency-input changes may
trigger one changed-input readiness recheck before validation. See
`08_Tooling/workflow-scheduler/docs/DEPENDENCY_READINESS.md`.

Earlier Workflow Scheduler milestones include Phase 1; 2A–2E; 3A–3F; WSC3;
WSC5B5; and WSC5B6. WSC3 validates supplied WSC1, IssuePlanCore, and GEX
evidence and emits immutable, unapproved proposal evidence. WSC5B5 exposes the
retained frozen-validation result beside the runtime outcome without rerunning
validation or adding authority. WSC5B6 adds validation-only execution to the
same lifecycle while reusing lease, worktree, cancellation, validation,
containment, cleanup, release, and quarantine contracts. See
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md`.

**Agent Memory & Context Budget Manager**
(`08_Tooling/agent-memory-context-manager/`) includes packaging metadata, a
local Python module, and pytest coverage for handoff packets, cache keys,
summaries, summary-cache helpers, lookup, and packet-to-cache writing. Current
phase evidence reaches Memory 1G local summary-cache write-from-packet helpers.
Scheduler integration, autonomous writes, vector DB, embeddings, REST API,
dashboard, daemon, and production deployment remain unsupported. Planning docs
remain in that module.

**IA4D-to-Scheduler Handoff Contract**
(`00_Governance/architecture-decisions/adr-0002-ia4d-scheduler-handoff-contract.md`
and its detail companions) remains `0.2.0`. WSC1 implements that contract in
`scripts/agent_os_issue_acceptance/scheduler_handoff.py`, supporting
`contract_version=0.2.0` and `planning_result_version=0.1.0`. It performs pure
local serialization, digesting, and validation only; it does not establish
freshness, authorize execution, or change Workflow Scheduler runtime. Future
version changes require approved change control.

**Agent OS Execution Service**
(`08_Tooling/agent-os-execution-service/`) moved `0.5.0` -> `0.6.0` under
WSC-AUTO1F (Issue #762). `authorized_validation_entrypoint.py` adds one thin
end-to-end entrypoint, `run_authorized_validation_lifecycle`, composing #757
admission, the existing `compose_and_run_validation` composition boundary
(extended additively with `pilot_result`/`workspace_lifecycle_evidence`/
`quarantine_packet` fields so #761 never re-runs the runtime for evidence it
already produced), and #761's bundle/terminal-result projection, in that
fixed order. It adds no runner, lease, containment, workspace, status model,
or retry logic of its own. Package metadata, `EXECUTION_SERVICE_VERSION`, and
registry records are aligned at `0.6.0`.

The same service moved `0.4.0` -> `0.5.0` under
AOS-CHATGPT2 (Issue #918). `executor_routing.py` adds one pure deterministic
execution-surface router for already-selected, already-authorized work. It owns
exactly four routes, twelve routing-only capabilities, immutable
`ExecutorRouteDecision` and `ExecutorHandoff`, finite reasons, canonical JSON,
content-addressed identities, and bounded opaque references to upstream
request, authorization, operating-mode, lane-selection, repository-state,
worktree, package, environment, checkpoint, resume, validation-plan, and
Workflow Scheduler evidence.

Routing precedence is exact: an explicit human-decision override wins first;
otherwise connector-native is selected when sufficient, the governed runner is
selected when available and capable, an external fallback is selected only when
explicitly permitted and available after runner insufficiency, and human
decision is selected otherwise. The router does not select work, validate
upstream semantic objects, widen authority, invoke a runner, execute a process,
persist checkpoints, call GitHub or a provider, or create a second capability,
authorization, validation, checkpoint, worktree, runner, or Scheduler framework.
Package metadata, `EXECUTION_SERVICE_VERSION`, and registry records are aligned
at `0.5.0`.

The same service moved `0.3.0` -> `0.4.0` under PILOT-VALIDATION (Issue #723).
`command_planning.py` added an exact pre-PR branch binding
`PrePrValidationSubject` and `PrePrValidationPlan` to an
`ExecutionServiceRequest` for validation-only candidate #726 without fabricating
a pull request. Existing positive-PR identities remain stable,
`COMMAND_REGISTRY_VERSION` remains `1.0`, authorization stays false, and the
30-second command and 300-second total ceilings remain enforced.

The service moved `0.2.0` -> `0.3.0` under WSC6B4 (Issue #697).
`execution_composition.py` added `compose_and_run_validation(...)`, a thin
non-authorizing boundary that revalidates request, plan, authorization, and
runtime identity before delegating exactly once to the canonical validation-only
Workflow Scheduler entrypoint. It adds no second runtime or command loop.

**Agent Interaction Output Standard**
(`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`,
#926) is the canonical owner of the base report field set, conditional routing
and GitHub field groups, the ten presentation profiles, visible ordering, and
progress labeling. `AGENTS.md`, `_common-overlay-rules.md`,
`final-report-standard.md`, and `07_Agent_Tests/agent-output-schema.md` are
compatibility pointers to it. It renders existing canonical evidence and adds no
state, approval, execution, or write authority.

## Reconciliation Notes

A3 reviewed the version map against visible repository evidence only. Runtime
status not directly supported by files or validation evidence remains unstated
rather than inferred.
