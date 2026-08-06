# Module Version Map — Details

Extended module descriptions moved out of `module-version-map.md` to keep that
index under the 100-line limit. See that file for the canonical version table.

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) version reflects
sixteen shipped milestones: Phase 1 (MVP), 2A (approval engine), 2B (retry
manager), 2C (pause/resume/cancel lifecycle), 2D (task batching), 2E
(opt-in parallel ready-list dispatch), 3A (GitHub read-only adapter), 3B
(Notion read-only adapter), 3C (GitHub approved comment adapter), 3D
(five-state result contract), 3E (GitHub approved label adapter), 3F
(adapter contract migration), and WSC3 (stateless draft-proposal ingestion).
WSC3 validates supplied WSC1, IssuePlanCore, and GEX evidence and emits only
immutable, unapproved proposal evidence. WSC5B5 adds a backward-compatible
bounded return contract exposing the exact retained frozen-validation result
alongside the canonical runtime outcome without rerunning validation or adding
execution authority. WSC5B6 adds one additive validation-only execution mode to
that same canonical lifecycle: it reuses the existing lease, worktree,
cancellation, validation, containment, cleanup, release, and quarantine
contracts, dispatches no executor and constructs no process executor, and
leaves standard-mode behavior unchanged. It does not create tasks, approvals,
queues, leases,
workers, dispatch state, persistence, or external I/O. See
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` for implementation details.

**Agent Memory & Context Budget Manager**
(`08_Tooling/agent-memory-context-manager/`) has moved beyond planning-only
status. Current disk evidence includes standard packaging metadata completed by
D1 (#122), a local Python module under `src/`, and pytest coverage under `tests/`
for handoff packet construction and validation, cache-key generation, packet
summaries, summary cache read/write helpers, summary cache lookup, and
packet-to-cache writing. Current phase evidence reaches Memory 1G local
summary-cache write-from-packet helpers.

Still unsupported or incomplete: Scheduler runtime integration, autonomous
writes, vector DB, embeddings, REST API, dashboard, daemon, and production
deployment. The planning documents remain part of the module: `README.md`,
`HANDOFF_PACKET_TEMPLATE.md`, `CONTEXT_BUDGET_POLICY.md`,
`SUMMARY_CACHE_FORMAT.md`, and `SCHEDULER_INTEGRATION_DESIGN.md`.

**IA4D-to-Scheduler Handoff Contract**
(`00_Governance/architecture-decisions/adr-0002-ia4d-scheduler-handoff-contract.md`
plus its `adr-0002-details-*` companions) remains version `0.2.0`. WSC1 implements
that existing contract in
`scripts/agent_os_issue_acceptance/scheduler_handoff.py`, supporting
`contract_version=0.2.0` and `planning_result_version=0.1.0`. The implementation
performs pure local serialization, digesting, and validation only; it does not
establish freshness, authorize execution, or change Workflow Scheduler runtime.
Future version changes require an approved standards or contract change under
`00_Governance/standards-change-control.md`.

**Agent OS Execution Service** (`08_Tooling/agent-os-execution-service/`) moved `0.4.0` -> `0.5.0` under AOS-CHATGPT2 (#918): `executor_routing.py` adds one pure, deterministic execution-surface router for already-selected and already-authorized work. It defines exactly four routes, a finite twelve-value routing-only `ExecutorCapability` enum, immutable `ExecutorRouteDecision` and shared `ExecutorHandoff` records, finite reason codes, canonical JSON, content-addressed identities, and bounded opaque references to existing request, authorization, operating-mode, lane-selection, repository-state, worktree, package, environment, checkpoint, resume, validation-plan, and Workflow Scheduler identities. Connector-native remains the lowest-cost sufficient route; the governed runner is preferred whenever it supports every required capability; external fallback requires explicit permission and availability; ambiguous, excluded, stale, contradictory, irreversible, or unsupported work routes to human decision. The router does not select work, validate upstream semantic objects, widen authority, invoke a runner, execute a process, persist checkpoints, call GitHub or a provider, or create a second capability, authorization, validation, checkpoint, worktree, runner, or Scheduler framework.

**Agent OS Execution Service** (`08_Tooling/agent-os-execution-service/`) moved `0.3.0` -> `0.4.0` under PILOT-VALIDATION (#723): `command_planning.py` allowlists one additional exact command and adds one explicit exact-type pre-PR branch that binds the immutable `PrePrValidationSubject` and additive `PrePrValidationPlan` from `scripts/agent_os_remote_validation/models.py` to an `ExecutionServiceRequest` for validation-only candidate #726, without fabricating a pull request. Positive-PR validation-plan and command-plan payloads and identities are unchanged, and `COMMAND_REGISTRY_VERSION` stays `1.0` because allowlisting a command is additive. Planning stays pure-local and non-authorizing: `execution_authorized`, `merge_authorized`, and `side_effects_performed` remain false, the 30-second per-command and 300-second total validation ceilings are enforced, #726 was not executed, and Scheduler concurrency remains `0`. Workflow Scheduler remains `0.9.0`.

**Agent OS Execution Service** moved `0.2.0` -> `0.3.0` under WSC6B4 (#697): `execution_composition.py` adds `compose_and_run_validation(...)`, a thin, non-authorizing boundary that revalidates request/plan/authorization/runtime identity and delegates exactly once to the canonical Workflow Scheduler validation-only entrypoint, retaining the exact `FrozenTestValidationResult`. No second runtime, command loop, or duplicate evidence model was added; `merge_authorized` stays false; execution authorization, validation, review, and merge authorization remain separate states. Workflow Scheduler remains `0.9.0`.
