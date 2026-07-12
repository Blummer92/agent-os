# Orchestration Rules

Canonical rules for routing teacher requests through the curriculum pipeline
without making every agent choose ownership, mode, context, reuse, and budget.

## Canonical Schema

Required input fields:
- teacher request
- available prior outputs
- write intent
- compute budget
- source of truth
- approval status

Required decisions:
- task owner
- mode: `Draft`, `Gate`, or `Production`
- context packet
- reusable outputs
- stop_or_continue
- next_owner

Allowed output keys:
- status: `ROUTED` or `BLOCKED`
- blockers
- task_owner
- mode
- context_packet
- reusable_outputs
- compute_budget
- stop_or_continue
- next_owner
- handoff_artifacts

Blocker behavior: if owner, mode, source of truth, write authority, or approval
status is unclear, stop immediately, set `status: BLOCKED`, name the blocker, and
route to `next_owner`. Do not ask a downstream agent to decide.

Handoff targets: Unit Alignment Agent, Teacher Modeling Coach, Instructional
Materials Coach, QA / Test Agent, or Workspace Automation Builder for
automation/release QA.

## Routing Rules

- Unit planning or alignment evidence routes to Unit Alignment Agent.
- Modeling, think-alouds, or worked examples route to Teacher Modeling Coach.
- Slides, worksheets, or student-facing materials route to Instructional
  Materials Coach.
- Validation, regression checks, or release review routes to QA / Test Agent.
- Automation, repository, or release-package QA routes to Workspace Automation
  Builder.
- Production writes require explicit approval before routing as `Production`.

## Context Rules

- Send only fields required by the selected owner and mode.
- Reuse prior approved outputs before requesting regeneration.
- Do not re-send full unit history when a handoff artifact is sufficient.
- Allocate the smallest compute budget that can complete the selected mode.

## Version

0.1.0
