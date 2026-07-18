# Agent Handoff Packet Template

## Purpose
Use this packet to give an agent the smallest verified working set before a bounded task.

## Canonical Fields
- `objective`: one-sentence goal
- `current_phase`: current phase and stage
- `branch`: active branch, or `null` before one exists
- `pr_number`: PR number, or `null` before one exists
- `changed_files`: files already changed
- `allowed_inspect_first`: files to read first
- `forbidden_unless_needed`: paths to avoid unless justified
- `known_facts`: verified facts
- `prior_decisions`: approved choices and rejected alternatives
- `acceptance_criteria`: pass/fail conditions
- `validation_commands`: exact validation commands
- `compute_limits`: canonical context and test limits
- `stop_conditions`: pause or escalation conditions

`pr_number: 0` is legacy-compatible only. New pre-PR packets use `null`.

## YAML Template
```yaml
objective: "<task goal>"
current_phase: "<phase and stage>"
branch: null
pr_number: null
changed_files: []
allowed_inspect_first: []
forbidden_unless_needed: []
known_facts: []
prior_decisions: []
acceptance_criteria: []
validation_commands: []
compute_limits:
  max_files_to_inspect: 8
  targeted_tests_only: true
  no_full_scheduler_suite: true
stop_conditions: []
```

Compute limits are declarations and stop obligations, not runtime enforcement.

## Existing-PR Example
```yaml
objective: "Review one documentation-only pull request"
current_phase: "review"
branch: "docs/review-handoff"
pr_number: 37
changed_files: ["README.md"]
allowed_inspect_first: ["README.md"]
forbidden_unless_needed: ["08_Tooling/workflow-scheduler/"]
known_facts: ["The pull request is documentation-only."]
prior_decisions: ["No source changes are authorized."]
acceptance_criteria: ["The documented command is accurate."]
validation_commands: ["bash 07_Agent_Tests/validate-repo-structure.sh"]
compute_limits:
  max_files_to_inspect: 3
  targeted_tests_only: true
  no_full_scheduler_suite: true
stop_conditions: ["Source or workflow changes appear."]
```

## Pre-Branch Example
```yaml
objective: "Plan one focused module update"
current_phase: "design refinement"
branch: null
pr_number: null
changed_files: []
allowed_inspect_first: ["08_Tooling/agent-memory-context-manager/README.md"]
forbidden_unless_needed: ["08_Tooling/workflow-scheduler/"]
known_facts: ["Memory Manager selects context; it does not schedule execution."]
prior_decisions: ["No Scheduler integration is in scope."]
acceptance_criteria: ["The implementation allowlist is exact."]
validation_commands: ["PYTHONPATH=src python -m pytest tests/test_handoff_packet.py -q"]
compute_limits:
  max_files_to_inspect: 6
  targeted_tests_only: true
  no_full_scheduler_suite: true
stop_conditions: ["The task requires a second module."]
```

## Stop Conditions
Stop when the working set is unclear, a declared limit is exceeded, authorization is missing, blocked tools are retried without new evidence, or unrelated cleanup enters scope.

## Non-Goals
No Scheduler integration, autonomous writes, generalized cache service, vector database, embeddings, REST API, dashboard, or daemon.
