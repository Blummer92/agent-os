# Agent Handoff Packet Template

## Purpose
This template gives agents the smallest useful working set before they start. It reduces compute by naming the objective, files to inspect first, known facts, validation commands, and explicit stop conditions.

## When to Use This Packet
Use this before code review, docs edits, small feature work, test triage, or PR validation. For large or unclear tasks, create a planning packet first instead of scanning the repo.

## Packet Fields
- `objective`: one-sentence goal
- `current_phase`: phase and stage of work
- `branch`: active git branch
- `pr_number`: PR number or `null`
- `changed_files`: files already changed
- `allowed_inspect_first`: files the agent should read first
- `forbidden_unless_needed`: files or folders to avoid unless justified
- `known_facts`: validated facts the agent should reuse
- `prior_decisions`: approved decisions and rejected alternatives
- `acceptance_criteria`: pass/fail conditions
- `validation_commands`: commands to verify the work
- `compute_limits`: maximum files, searches, test runs, connector calls
- `stop_conditions`: conditions that require pausing or escalation

## YAML Template
```yaml
objective: "<task goal>"
current_phase: "<phase and stage>"
branch: "<git branch>"
pr_number: null
changed_files: []
allowed_inspect_first: []
forbidden_unless_needed: []
known_facts: []
prior_decisions: []
acceptance_criteria: []
validation_commands: []
compute_limits:
  max_files: 7
  max_searches: 5
  max_test_runs: 1
  max_connector_calls: 0
stop_conditions: []
```

## Small Task Example
```yaml
objective: "Review one docs-only PR for scope accuracy"
current_phase: "Memory 0B review"
branch: "claude/agent-memory-context-manager-0b-handoff-template"
pr_number: 37
changed_files:
  - "08_Tooling/agent-memory-context-manager/HANDOFF_PACKET_TEMPLATE.md"
allowed_inspect_first:
  - "08_Tooling/agent-memory-context-manager/README.md"
forbidden_unless_needed:
  - "08_Tooling/workflow-scheduler/src/"
  - "tests/"
known_facts:
  - "Memory Manager selects context; Workflow Scheduler executes tasks."
acceptance_criteria:
  - "One docs-only file under 100 lines."
validation_commands:
  - "manual diff review"
compute_limits: {max_files: 3, max_searches: 2, max_test_runs: 0, max_connector_calls: 1}
stop_conditions:
  - "Source or test changes appear."
```

## Medium Task Example
```yaml
objective: "Plan a focused docs update for one tooling module"
current_phase: "Design refinement"
branch: "claude/example-medium-docs-task"
pr_number: null
changed_files: []
allowed_inspect_first:
  - "08_Tooling/agent-memory-context-manager/README.md"
  - "04_Registry/module-version-map.md"
forbidden_unless_needed:
  - "08_Tooling/workflow-scheduler/src/"
known_facts:
  - "Large tasks require planning before scanning."
prior_decisions:
  - "No embeddings, REST API, dashboard, or daemon yet."
acceptance_criteria:
  - "Scope remains docs-only and focused on one module."
validation_commands:
  - "bash 07_Agent_Tests/validate-repo-structure.sh"
compute_limits: {max_files: 12, max_searches: 6, max_test_runs: 1, max_connector_calls: 2}
stop_conditions:
  - "More than 15 files are needed."
  - "The task becomes implementation work."
```

## Stop Conditions
Stop when context budget is exceeded, target files are unclear, auth or approval fails, tests fail repeatedly without new evidence, full-repo search is requested before targeted search, or unrelated cleanup is proposed.

## Non-Goals
No code implementation. No schema validator. No Python module. No Scheduler integration. No autonomous writes. No vector DB. No embeddings. No REST API. No dashboard. No daemon. No Phase 4 adapter-contract work.