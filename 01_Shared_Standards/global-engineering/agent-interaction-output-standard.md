# Agent Interaction Output Standard
## Purpose
One canonical Agent OS contract for what a governed response must report and how it is visibly ordered. It renders existing canonical evidence into a situation-appropriate answer and creates no operational state, readiness, approval, execution, or write authority.

## Authority And Precedence
1. Governance stop conditions and write authorization control first (`00_Governance/`).
2. Canonical contracts own field values: IssueOperationalState, AgentOperatingModeDecision, executor route, post-PR state audit, validation evidence, `01_Shared_Standards/github/sprint-reporting-schema.md`, approval, projection, and Scheduler records.
3. This standard owns the required field set, presentation profiles, visible ordering, and progress labeling.
4. Domain presentation standards refine one profile without changing field ownership or authority: `artifact-first-response-standard.md`, `teacher-decision-studio-standard.md`, and `teacher-decision-studio-previews-standard.md`.
5. `AGENTS.md`, `02_Agent_Overlays/_common-overlay-rules.md`, `final-report-standard.md`, and `07_Agent_Tests/agent-output-schema.md` are compatibility pointers; test documentation verifies this standard and is never an independent policy source.

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

`status` is `blocked` only with a non-empty `blockers`, and `deferred` only with a real `next_owner`. Visible prose may omit an empty or immaterial field; omission never removes it from required report evidence.

## Conditional Field Groups
Routing fields apply only when routing is material: `task_owner`, `selected_overlay`, `standards_read`, `allowed_actions`, `blocked_actions`, `context_packet`, and `stop_conditions`.
GitHub implementation fields apply only when repository implementation or review is material: repository, issue, branch, pull request, source or exact head, validation state, current stage, and next action. No profile is required to display every field.

## Presentation Profiles
| Profile | Lead with |
|---|---|
| Simple status | the direct answer |
| GitHub read-only investigation | verified status or blocker, then evidence and the smallest next action |
| Issue implementation | bounded state-based progress when canonical stages exist, then completed, current, remaining, blockers rendered as `Completed`, `Current`, `Remaining`, `Blockers`, then a material execution route as `Best execution`, then one supported next action |
| PR review or terminal handoff | review state and exact-head evidence, then the same compact block when bounded stages exist, then handoff |
| Blocked work | the controlling blocker and its exact unblock condition |
| Prompt or command delivery | one reusable copy/paste artifact — the smallest reusable context packet that executes safely |
| Architecture review | the verdict, then evidence, risks, roadmap, and report |
| Classroom artifact | the requested artifact, preview, or content specification |
| Scheduled monitoring | the resolved target and its actual scheduled behavior |
| Read-only handoff | the verified finding, then recipient and next action |

Internal governance and source checks run before the response but never displace the profile's leading output unless a stop condition applies; governance and report fields follow it.

Classroom-artifact receipts order their available surfaces as live artifact link -> current preview or export -> genuine before/after evidence -> change and QA summary -> evidence limitations -> governance fields. Never fabricate unavailable historical visual evidence.

## Compact Operator Rendering
- For implementation/review, label canonical evidence as `Completed`, `Current`, `Remaining`, and `Blockers`: `Completed` = completed named stages; `Current` = canonical current stage; `Remaining` = unfinished stages in the bounded sequence and is distinct from `remaining_risks`; `Blockers` = Base Report Contract `blockers`.
- Render a state-based progress bar only when canonical evidence exposes a bounded named stage sequence. Segments represent those stage slots, not a percentage, score, persisted progress record, or independent lifecycle model; omit the bar when no bounded sequence exists.
- Show `Best execution` only when executor-route/capability evidence is material. Prefer one `Next` action only when current canonical evidence supports one; otherwise omit it rather than inventing work.
- Prompt/command delivery uses the smallest reusable context packet that executes safely. Do not repeat governance, source-of-truth, architecture, or repository boilerplate already available to the target unless material to the exact action.
- Compact rendering never hides a controlling blocker, authorization boundary, owner/source-of-truth constraint, exact-head requirement, validation failure, or required final-report evidence.

## Progress And Evidence Rules
- Render progress from named canonical states and evidence. Never persist a parallel progress record, workflow-state engine, or conversation-state service.
- Label a material progress claim `verified`, `inferred`, `proposed`, `blocked`, or `completed`.
- Reject percentages unless a canonical contract supplies the completion signal.
- Conversation memory may carry target identifiers but never overrides live canonical evidence.
- Presentation never implies execution authority, and a recommendation is never reported as executed.

## Version
0.2.0
