# Agent Interaction Output Standard

## Purpose

One canonical Agent OS contract for what a governed response must report and how
that response is visibly ordered. It renders existing canonical evidence into a
situation-appropriate answer. It creates no operational state, readiness,
approval, execution, or write authority.

## Authority And Precedence

1. Governance stop conditions and write authorization control first (`00_Governance/`).
2. Canonical contracts own field values: IssueOperationalState,
   AgentOperatingModeDecision, executor route, post-PR state audit, validation
   evidence, `01_Shared_Standards/github/sprint-reporting-schema.md`, approval,
   projection, and Scheduler records.
3. This standard owns the required field set, presentation profiles, visible
   ordering, and progress labeling.
4. Domain presentation standards refine one profile without changing field
   ownership or authority: `artifact-first-response-standard.md`,
   `teacher-decision-studio-standard.md`, and
   `teacher-decision-studio-previews-standard.md`.
5. `AGENTS.md`, `02_Agent_Overlays/_common-overlay-rules.md`,
   `final-report-standard.md`, and `07_Agent_Tests/agent-output-schema.md` are
   compatibility pointers. Test documentation verifies this standard and is
   never an independent policy source.

## Base Report Contract

| Field | Meaning | Value owner |
|---|---|---|
| `status` | `pass`, `fail`, `blocked`, or `deferred` | this standard |
| `blockers` | controlling stop conditions; empty when none | governance stop conditions |
| `checks_passed` | governance or validation checks that passed | validation evidence |
| `checks_failed` | checks that failed; empty when none | validation evidence |
| `next_owner` | registered next owner, or `None` | `04_Registry/` routing |
| `handoff_artifacts` | records or links passed forward | the owning workflow |
| `files_changed` | files modified; empty when read-only | repository evidence |
| `tests_run` | executed tests, or `N/A` | validation evidence |
| `docs_updated` | documentation changed; empty when none | repository evidence |
| `remaining_risks` | known residual risk; empty when none | the reporting agent |

`status` is `blocked` only with a non-empty `blockers`, and `deferred` only with
a real `next_owner`. Visible prose may omit an empty or immaterial field;
omission never removes it from required report evidence.

## Conditional Field Groups

Routing fields apply only when routing is material: `task_owner`,
`selected_overlay`, `standards_read`, `allowed_actions`, `blocked_actions`,
`context_packet`, and `stop_conditions`.

GitHub implementation fields apply only when repository implementation or review
is material: repository, issue, branch, pull request, source or exact head,
validation state, current stage, and next action.

No profile is required to display every field.

## Presentation Profiles

| Profile | Lead with |
|---|---|
| Simple status | the direct answer |
| GitHub read-only investigation | verified status or blocker, then evidence and the smallest next action |
| Issue implementation | completed, current, remaining, blockers, execution route, then next action |
| PR review or terminal handoff | terminal or review state with exact-head evidence, then the handoff |
| Blocked work | the controlling blocker and its exact unblock condition |
| Prompt or command delivery | one reusable copy/paste artifact |
| Architecture review | the verdict, then evidence, risks, roadmap, and report |
| Classroom artifact | the requested artifact, preview, or content specification |
| Scheduled monitoring | the resolved target and its actual scheduled behavior |
| Read-only handoff | the verified finding, then recipient and next action |

Internal governance and source checks run before the response but never displace
the profile's leading output unless a stop condition applies; governance and
report fields follow it.

Classroom-artifact receipts order their available surfaces as live artifact link
-> current preview or export -> genuine before/after evidence -> change and QA
summary -> evidence limitations -> governance fields. Never fabricate
unavailable historical visual evidence.

## Progress And Evidence Rules

- Render progress from named canonical states and evidence. Never persist a
  parallel progress record, workflow-state engine, or conversation-state service.
- Label a material progress claim `verified`, `inferred`, `proposed`, `blocked`,
  or `completed`.
- Reject percentages unless a canonical contract supplies the completion signal.
- Conversation memory may carry target identifiers but never overrides live
  canonical evidence.
- Presentation never implies execution authority, and a recommendation is never
  reported as executed.

## Version

0.1.0
