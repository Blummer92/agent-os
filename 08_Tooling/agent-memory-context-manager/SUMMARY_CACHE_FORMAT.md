# Summary Cache Format

## Purpose
This document defines a simple summary cache format for Agent Memory & Context Budget Manager. The cache helps agents avoid re-reading unchanged files and re-discovering validated facts.

## Cache Principles
- Text-first and human-readable.
- Local and advisory, not an external source of truth.
- Source files, tests, PRs, and user decisions remain authoritative.
- No vector database, embeddings, daemon, or automatic repo scan.
- Cached entries must record their source and validation time.
- Stale summaries must be ignored or refreshed before use.

## Cache Entry Types
- **Project summary**: stable architecture, conventions, repo rules.
- **Phase summary**: current phase goals, completed milestones, blockers.
- **PR summary**: branch, PR number, changed files, validation state.
- **File summary**: purpose and important details for one file.
- **Test summary**: relevant tests and recent pass/fail state.
- **Decision summary**: approved choices and rejected alternatives.
- **Risk summary**: known hazards, blockers, unsupported features.

## File Summary Entry
```yaml
id: file:08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md
type: file_summary
source_path: 08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md
summary: "Explains Scheduler responsibilities and execution flow."
validated_at: "2026-07-13T00:00:00Z"
validated_by: "agent"
source_sha: "<git blob sha or commit sha>"
stale: false
notes: []
```

## Test Summary Entry
```yaml
id: test:workflow_scheduler.executor
type: test_summary
source_path: tests/workflow_scheduler/test_executor.py
summary: "Covers Executor lease, governance, adapter result handling, and dispatch behavior."
validated_at: "2026-07-13T00:00:00Z"
validated_by: "agent"
content_hash: "<hash of relevant test file>"
stale: false
notes: ["Run targeted tests before full suite."]
```

## Decision Summary Entry
```yaml
id: decision:memory-manager-separate-module
type: decision_summary
source_ref: "Memory 0A"
summary: "Memory Manager is a companion module; Scheduler still executes tasks."
validated_at: "2026-07-13T00:00:00Z"
validated_by: "user-approved PR"
source_sha: "<merge commit sha>"
stale: false
notes: ["Do not fold context selection into Scheduler core yet."]
```

## Risk Summary Entry
```yaml
id: risk:connector-retry-compute-waste
type: risk_summary
source_ref: "Memory 0C"
summary: "Repeated connector retries after auth or approval failure waste compute."
validated_at: "2026-07-13T00:00:00Z"
validated_by: "policy doc"
source_sha: "<merge commit sha>"
stale: false
notes: ["Escalate instead of retrying blocked tools."]
```

## Invalidation Rules
- Invalidate file summaries when the source file changes.
- Invalidate test summaries when related test files change.
- Invalidate PR summaries when the branch head changes.
- Invalidate phase summaries when phase status changes.
- Invalidate decision summaries only when superseded by a later decision.
- Invalidate risk summaries when the risk is resolved or changes scope.
- Mark stale entries explicitly; do not silently reuse stale summaries.

## Example Cache Entries
Use the entry blocks above as the initial text format. Future phases may store entries as Markdown, YAML, JSON, or another local text format, but the required fields should remain stable.

## Non-Goals
No code implementation. No schema validator. No Python module. No Scheduler integration. No autonomous writes. No vector DB. No embeddings. No REST API. No dashboard. No daemon. No Phase 4 adapter-contract work.