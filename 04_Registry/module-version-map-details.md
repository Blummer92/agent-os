# Module Version Map — Details

Extended module descriptions moved out of `module-version-map.md` to keep that
index below 100 lines. See that file for the canonical version table.

**Workflow Scheduler** (`08_Tooling/workflow-scheduler/`) now includes the
WSC-AUTO2A (#722) bounded Claude Code CLI adapter at version `0.14.0`. The
adapter consumes caller-supplied #934 Implementation Packet/source identities
plus exact provider path/version/auth-status evidence and produces one
deterministic non-shell argv tuple. It permits only file read/edit/write/search
tools, explicitly disallows Bash, web tools, and MCP, disables session/Chrome/
slash-command surfaces, bounds turns and prompt/output sizes, and normalizes
already-executed JSON results into non-authorizing terminal evidence without
retaining provider prose. It performs no provider launch, credential lookup,
network access, worktree/lease/containment lifecycle, validation, retry, GitHub
write, merge, or issue closure. The existing Workflow Scheduler runtime remains
the sole process/worktree/validation lifecycle; #935 owns the first live coding
pilot. Earlier WSC milestones remain unchanged; see
`08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md` and
`docs/CLAUDE_CODE_EXECUTOR_ADAPTER.md`.

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

The same service moved `0.4.0` -> `0.5.0` under AOS-CHATGPT2 (Issue #918).
`executor_routing.py` owns the pure deterministic four-route executor selector
and immutable `ExecutorRouteDecision`/`ExecutorHandoff` records. It does not
invoke a runner or provider; #722 supplies the first concrete coding-provider
binding without changing #918 ownership.

The service moved `0.3.0` -> `0.4.0` under PILOT-VALIDATION (Issue #723) for
exact pre-PR validation subject/plan binding, and moved `0.2.0` -> `0.3.0` under
WSC6B4 (Issue #697) for the thin validation composition boundary.

**Agent Interaction Output Standard**
(`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`,
#926) is the canonical owner of report field ownership, presentation profiles,
visible ordering, and evidence-grounded progress labeling. Compact operator
rendering was added in #1081 without creating new progress state or authority.

## Reconciliation Notes

A3 reviewed the version map against visible repository evidence only. Runtime
status not directly supported by files or validation evidence remains unstated
rather than inferred.
