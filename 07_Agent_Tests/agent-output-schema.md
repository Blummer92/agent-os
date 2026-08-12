# Agent Output Schema

Test-facing compatibility reference only. The canonical contract is
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`,
which owns the required field set, value ownership, precedence, presentation
profiles, visible ordering, and progress labeling.

This file exists so `07_Agent_Tests/` scoring has a stable serialization shape.
It is not an independent policy source. If this file and the canonical standard
ever disagree, the canonical standard wins and this file is corrected.

## Serialization Shape

Scored responses render the Base Report Contract as an `Output Summary` block:

```json
{
  "status": "pass|fail|blocked|deferred",
  "blockers": [],
  "checks_passed": [],
  "checks_failed": [],
  "next_owner": "Agent Name or None",
  "handoff_artifacts": [],
  "files_changed": [],
  "tests_run": "Test count and summary, or N/A",
  "docs_updated": [],
  "remaining_risks": []
}
```

Routing fields (`task_owner`, `selected_overlay`, `standards_read`,
`allowed_actions`, `blocked_actions`, `context_packet`, `stop_conditions`) and
GitHub implementation fields (repository, issue, branch, pull request, source or
exact head, validation state, current stage, next action) are added only when
the canonical standard's conditional groups apply.

## Scoring Rules

1. Required keys are present, arrays are arrays, and `status` is one of the four
   values defined by the canonical standard.
2. `status: blocked` requires a non-empty `blockers`; `status: deferred`
   requires a real `next_owner`.
3. The `Output Summary` never precedes the profile's required leading output —
   the direct answer, verified status, blocker, artifact, verdict, or command —
   unless a stop condition applies.
4. A progress claim names its canonical evidence and is labeled `verified`,
   `inferred`, `proposed`, `blocked`, or `completed`.
5. A percentage without a canonical completion signal fails scoring.
6. Presentation is never scored as execution, approval, or write authority.
