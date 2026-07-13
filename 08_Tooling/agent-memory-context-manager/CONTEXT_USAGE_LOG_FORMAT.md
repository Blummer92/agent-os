# Context Usage Log Format

## Purpose
This document defines a future local context usage log format for Agent Memory & Context Budget Manager. The log records what context an agent used during a task. It does not implement logging.

## Relationship to Memory 1A
- Memory 1A packet generator is planned but paused until a local runner is available.
- Memory 1B remains docs-only.
- This format is for a future Memory 1B implementation.
- Do not create implementation code or tests from this document alone.

## Log Principles
- Text-first, human-readable, and local-first.
- Append-only by default and audit-friendly.
- No background daemon, automatic repo scan, vector DB, or embeddings.
- Source files remain authoritative.
- Logs record context usage; they do not approve or execute tasks.

## Event Types
- `context_packet_generated`
- `file_inspected`
- `search_used`
- `test_run`
- `connector_used`
- `summary_reused`
- `summary_marked_stale`
- `budget_escalation_requested`
- `stop_condition_triggered`

## Required Fields
Each event should include `event_id`, `event_type`, `task_id` or `task_ref`, `phase`, `timestamp`, `actor`, `source_ref`, `details`, `budget_snapshot`, and `notes`.

## Context Packet Event
Records when a handoff packet is generated, including allowed files, forbidden files, compute limits, validation commands, and stop conditions.

## File Inspection Event
Records each file inspected, why it was read, whether it was allowed by the packet, and whether the read changed known context.

## Search Usage Event
Records search query, scope, result count, reason, and whether the search stayed within the packet budget.

## Test Usage Event
Records test command, target path, result, reason, and whether the command was targeted or broader than planned.

## Connector Usage Event
Records connector name, action type, source ref, result summary, and whether the call was required by the packet.

## Budget Escalation Event
Records the requested budget increase, reason, original budget, smallest proposed expanded budget, and approval status if known.

## Stop Condition Event
Records which stop condition triggered, what evidence caused it, and what the agent should ask before continuing.

## Example Log Entries
```yaml
- event_id: evt-001
  event_type: context_packet_generated
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: HANDOFF_PACKET_TEMPLATE.md
  details: {allowed_files: 3, stop_conditions: 3}
  budget_snapshot: {max_files_to_inspect: 8, targeted_tests_only: true}
  notes: []
- event_id: evt-002
  event_type: file_inspected
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: README.md
  details: {reason: "confirm scope", within_budget: true}
  budget_snapshot: {files_inspected: 1, max_files_to_inspect: 8}
  notes: []
- event_id: evt-003
  event_type: search_used
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: local_repo
  details: {query: "handoff packet", result_count: 2}
  budget_snapshot: {searches_used: 1}
  notes: []
- event_id: evt-004
  event_type: test_run
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: tests/test_handoff_packet.py
  details: {command: "pytest .../test_handoff_packet.py", result: "pass"}
  budget_snapshot: {targeted_tests_only: true}
  notes: []
- event_id: evt-005
  event_type: budget_escalation_requested
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: Context Budget Policy
  details: {requested_files: 10, original_limit: 8, approval_status: "unknown"}
  budget_snapshot: {max_files_to_inspect: 8}
  notes: ["Ask before continuing."]
- event_id: evt-006
  event_type: stop_condition_triggered
  task_ref: issue-46
  phase: Memory 1A
  timestamp: "2026-07-13T00:00:00Z"
  actor: agent
  source_ref: HANDOFF_PACKET_TEMPLATE.md
  details: {condition: "Need Scheduler source changes"}
  budget_snapshot: {scheduler_files_allowed: false}
  notes: ["Stop and escalate."]
```

## Non-Goals
No code implementation. No tests. No Memory 1A implementation. No Scheduler integration. No Executor changes. No TaskAdapter changes. No adapter changes. No autonomous writes. No vector DB. No embeddings. No REST API. No dashboard. No daemon. No production deployment. No Phase 4 adapter-contract work.