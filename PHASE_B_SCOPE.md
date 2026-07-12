# Phase B: Workflow Scheduler MVP — Phase 1 Scope

**Date**: 2026-07-12  
**Base Branch**: `claude/workflow-scheduler-task-99sk7d` (Part A complete)  
**Implementation Branch**: `claude/workflow-scheduler-mvp`  
**Status**: Ready for Phase 1 MVP implementation

---

## Part A Prerequisites: ✅ COMPLETE

Before starting Phase B, verify Part A is merged or rebased:
- [x] Unit Alignment gate wording fixed (Tier 1 vs Tier 2 clarified)
- [x] Overlay contract verified (all 10 overlays compliant)
- [x] IMC inheritance verified (version 0.3.0, instructional-design standards)
- [x] Prompt templates verified (thin wrapper, no duplication)
- [x] Output schema implemented (8 required keys in common-test-checklist)

**Part A enables**: Agents can now self-verify compliance using machine-checkable output schema.

---

## Phase 1 MVP: Narrow Scope

### ✅ BUILD IN PHASE 1

**Models** (`src/workflow_scheduler/models/`):
- `task.py` — Task model with status enum (draft, pending, approval_pending, approved, queued, running, retry_scheduled, completed, failed, governance_blocked, paused, cancelled)
- `workflow.py` — WorkflowPlan model (workflow_id, title, created_by, mode, tasks, dependencies)

**Storage** (`src/workflow_scheduler/repository/`):
- `sqlite_repository.py` — SQLite-backed persistence (workflows, tasks, audit events)
- Abstract repository interface (for future Postgres migration)

**Execution** (`src/workflow_scheduler/queue/`, `src/workflow_scheduler/dependencies/`, `src/workflow_scheduler/execution/`):
- `job_queue.py` — Basic priority queue (enqueue, dequeue, peek)
- `resolver.py` — Dependency resolver (build graph, detect cycles, identify ready tasks)
- `stop_conditions.py` — Stop condition checker (ambiguous target, missing auth, source-of-truth conflict, governed field risk)
- `executor.py` — Task executor with lease lock (acquire, execute, release)

**Adapters** (`src/workflow_scheduler/adapters/`):
- `base_adapter.py` — TaskAdapter interface
- `noop_adapter.py` — No-op adapter for testing (always succeeds, logs)

**Audit** (`src/workflow_scheduler/audit/`):
- `audit_logger.py` — State transition logging (creation, approval, execution, failure, completion)

**CLI** (`src/workflow_scheduler/cli.py`):
- `create` — Create workflow from YAML
- `list` — List workflows
- `status` — Get workflow status
- `run` — Execute workflow
- `audit` — View audit log

**Tests** (`tests/`):
- `test_task_model.py` — Task creation, validation, status transitions
- `test_workflow_model.py` — Workflow creation, task management
- `test_job_queue.py` — Queue operations (enqueue, dequeue, priority ordering)
- `test_dependency_resolver.py` — Cycle detection, ready-task identification
- `test_stop_conditions.py` — All 4 stop conditions
- `test_executor.py` — Execution, lease acquisition, result handling
- `test_audit_logger.py` — Event logging, filtering, timestamps
- `test_cli.py` — CLI command execution

**Documentation**:
- `docs/WORKFLOW_SCHEDULER.md` — User guide, quick start, common patterns
- `docs/ARCHITECTURE.md` — Component overview, data flow
- `docs/API_REFERENCE.md` — Python API for each component

**Example**:
- `examples/dashboard-sync-workflow.yaml` — Reference workflow using dashboard sync pattern from registry

**Acceptance Criteria**:
- All 8 components implemented
- Unit tests pass; 80%+ coverage
- No governance violations
- NoopAdapter works for testing
- CLI commands functional
- Dashboard sync workflow successfully executes through scheduler

---

### ⏸️ DEFER TO PHASE 2+

**Approval Engine** (Phase 2):
- Approve/deny task gates
- Ownership verification from registry
- Human approval dashboard stub

**Retry Manager** (Phase 2):
- Exponential backoff calculation
- Transient vs permanent failure classification
- Retry scheduling

**Job Management** (Phase 2+):
- Pause/resume with state preservation
- Cancellation with cascade to dependents
- Long-running job progress tracking
- Progress checkpoints

**Batching** (Phase 2+):
- Group similar tasks
- Batch execution optimization

**Parallel Execution** (Phase 2+):
- ExecutorPool for concurrent execution
- DependencyGraph for parallelism analysis
- Thread-safe execution

**Real Adapters** (Phase 2+):
- AgentAdapter for live agent invocation
- ToolAdapter for REST APIs/tools

**REST API** (Phase 3+):
- HTTP wrapper around Python interfaces
- Authentication/authorization
- Request validation

**Dashboard UI** (Phase 3+):
- Workflow monitoring dashboard
- Real-time task status
- Audit trail viewer

---

## Implementation Order

1. **Models** (Task, WorkflowPlan) — Foundation
2. **Repository** (SQLite storage) — Persistence
3. **Queue** (Basic FIFO) — Task management
4. **Dependency Resolver** — Execution ordering
5. **Stop Conditions** — Governance enforcement
6. **Executor** (with lease lock) — Task execution
7. **Audit Logger** — Compliance record
8. **NoopAdapter** — Testing harness
9. **CLI** — User interface
10. **Tests** — Validation
11. **Documentation** — Guidance
12. **Example** — Reference implementation

---

## Key Constraints

### Write Safety
- Default to read-only (from `00_Governance/write-authorization-policy.md`)
- Stop conditions checked BEFORE execution (ambiguous target, missing auth, conflicting records)
- Governance failures logged as `governance_blocked`, never retried

### Idempotency
- Every task includes `idempotency_key`
- Adapter responsible for deduplication
- Prevents duplicate writes on retry

### Lease Locks
- Running tasks hold timestamp-based lease
- Prevents concurrent execution of same task
- Lock timeout: 5 minutes (configurable)

### State Machine
- Task states: draft → pending → approval_pending → approved → queued → running → completed
- Branching paths: governance_blocked, failed, retry_scheduled, paused, cancelled
- All transitions logged in audit trail

---

## Dependencies

**External**:
- Python 3.8+
- sqlite3 (built-in)
- pytest (testing)
- pyyaml (workflow YAML parsing)

**Internal** (from Part A):
- `02_Agent_Overlays/_common-overlay-rules.md` (stop conditions)
- `04_Registry/ownership-matrix.md` (for future ownership verification)
- `07_Agent_Tests/agent-output-schema.md` (output validation)
- `07_Agent_Tests/common-test-checklist.md` (compliance rules)

---

## Handoff Readiness

✅ Part A foundation complete  
✅ Stop conditions defined in overlays  
✅ Output schema established  
✅ Governance rules documented  
✅ Example workflow available  

**Ready to implement Phase 1 MVP.**

---

## Next Agent Instructions

**Start here**: Implement Workflow Scheduler MVP Phase 1 only.

**Base**: Branch from `claude/workflow-scheduler-task-99sk7d` (Part A complete)  
**New branch**: `claude/workflow-scheduler-mvp`  
**Scope**: Phase 1 only (models, queue, resolver, stops, audit, executor, adapter, CLI)  
**DO NOT**: Add approvals, retries, pause/resume, batching, parallel, real adapters, REST API, or dashboard  

**Success**: All Phase 1 components pass tests with 80%+ coverage; dashboard sync workflow executes successfully.

---

## Verification Before Committing

```bash
# Unit tests
pytest tests/ -v

# Coverage (minimum 80%)
pytest --cov=src/workflow_scheduler tests/

# Lint
ruff check src/

# Type checking
mypy src/workflow_scheduler/

# Governance compliance
# Verify: No writes to blocked surfaces, stop conditions enforced, audit logged
```

---

## Reference Files

| File | Purpose |
|------|---------|
| `02_Agent_Overlays/_common-overlay-rules.md` | Stop conditions & governance rules (inherit) |
| `04_Registry/ownership-matrix.md` | Agent ownership (future use) |
| `00_Governance/write-authorization-policy.md` | Read-only default policy |
| `07_Agent_Tests/agent-output-schema.md` | Output validation schema |
| `07_Agent_Tests/common-test-checklist.md` | Compliance checklist |
| `01_Shared_Standards/instructional-design/README.md` | Curriculum pipeline example |

