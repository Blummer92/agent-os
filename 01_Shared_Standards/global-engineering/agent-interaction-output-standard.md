# Agent Interaction Output Standard

## Purpose

Own one canonical Agent OS interaction-output contract for machine-checkable
report evidence and situation-appropriate visible presentation. This standard
renders existing canonical evidence; it does not create operational state,
authorization, readiness, approval, or execution authority.

## Architecture

```text
canonical operational/domain evidence
-> Agent Interaction Output Standard
-> situation-specific presentation profile
-> concise user-facing rendering
```

Existing operational, approval, validation, executor-route, post-PR, sprint,
Scheduler, artifact, and domain contracts remain canonical for their evidence.

## Base Evidence Contract

Governance-gated reports preserve these fields in machine-checkable/report
evidence: `status`, `blockers`, `checks_passed`, `checks_failed`, `next_owner`,
`handoff_artifacts`, `files_changed`, `tests_run`, `docs_updated`, and
`remaining_risks`.

Visible prose may omit empty or irrelevant fields. Omission from visible prose
does not remove the field from required report evidence when the governing task
requires a machine-checkable summary.

Routing fields are conditional: `task_owner`, `selected_overlay`,
`standards_read`, `allowed_actions`, `blocked_actions`, `context_packet`, and
`stop_conditions` appear only when routing is material.

GitHub implementation fields are conditional: repository, issue, branch, pull
request, source or exact head, validation state, current stage, and next action
appear only when repository implementation or review is material.

## Presentation Profiles

| Profile | Lead with |
|---|---|
| Simple status | Direct verified answer |
| GitHub read-only investigation | Verified status or controlling blocker, then evidence and smallest next action |
| Issue implementation | Completed/current/remaining/blockers, execution route, then next action |
| PR review / post-PR handoff | Review or terminal state, exact-head evidence, blocker, then handoff |
| Blocked work | Controlling blocker and exact unblock condition |
| Prompt / command delivery | One reusable copy/paste artifact |
| Architecture review | Verdict, then evidence, risks, roadmap, and report |
| Classroom artifact | Requested/live artifact evidence before governance reporting |
| Scheduled monitoring | Resolved target and actual scheduled behavior |
| Read-only handoff | Verified finding, bounded evidence, then recipient and next action |

Internal governance checks may run first, but they must not displace the profile's
primary user-facing output unless a stop condition applies.

## Classroom Artifact Profile

When available and relevant, order evidence as: live/requested artifact ->
preview or export -> genuine before/after evidence -> change and QA summary ->
evidence limitations -> governance/final-report details.

Never fabricate unavailable historical visual evidence. Preserve
`artifact-first-response-standard.md` and Teacher Decision Studio behavior by
reference. Issue #960 owns Drive/Slides/Docs receipt mechanics, export capability,
historical visual retrieval, and detailed before/after evidence behavior.

## Progress And Evidence Rules

- Render progress from named canonical state and evidence; do not persist a new
  progress-state record.
- Prefer named stages/states over percentages. Use a percentage only when a
  canonical contract supplies a valid completion signal for it.
- Distinguish `verified`, `inferred`, `proposed`, `blocked`, and `completed`
  claims when the distinction is material.
- Conversation memory may retain identifiers but never overrides live canonical
  evidence.
- Presentation never creates execution, readiness, approval, merge, publication,
  external-write, or production authority.

## Precedence And Compatibility

Safety and canonical stop conditions control before presentation. Then apply the
matching profile. Domain presentation standards may refine that profile without
changing field ownership or authority.

`AGENTS.md`, `_common-overlay-rules.md`, `final-report-standard.md`, and
`07_Agent_Tests/agent-output-schema.md` are compatibility/reference surfaces for
this standard; they must not define a competing output contract.

Specialized sprint, executor-route, post-PR, approval, projection, validation,
and Scheduler records remain canonical evidence sources rather than alternate
interaction-output schemas.

## Version

0.1.0
