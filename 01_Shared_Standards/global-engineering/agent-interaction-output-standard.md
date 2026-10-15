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
- Prompt/command delivery uses the smallest reusable context packet that executes safely. When the user explicitly asks for console, shell, GitHub CLI, or other executable commands, return executable commands rather than conversational prompts; keep connected sequences short and reuse variables/context where that reduces repeated typing. Name the command surface (for example `bash` with the GitHub CLI `gh`) and keep explanatory text outside the commands so the result runs as given. Default investigation commands to read-only unless mutation is separately requested and authorized. Do not repeat governance, source-of-truth, architecture, or repository boilerplate already available to the target unless material to the exact action. When the user explicitly asks for a reusable next-step prompt intended for another chat or tool, render the complete self-contained prompt as one fenced copy-ready block, with explanation outside the fence. Do not use a Markdown blockquote for that reusable payload, and do not place citations, UI markup, or commentary inside it. When the reusable payload itself contains fenced code examples, delimit the outer copy-ready block with a fence strictly longer than any fence run inside the payload, so embedded examples cannot split the block and no payload text escapes the copy-ready region. When the request calls for a comparative A/B test to be run as independent runs, emit one complete copy-ready prompt per arm, labeled Arm A and Arm B, each satisfying this reusable-prompt contract; experiment analysis or orchestration may follow the runnable prompts but never replaces them. Ordinary prose remains unchanged when no reusable prompt is requested.
- Compact rendering never hides a controlling blocker, authorization boundary, owner/source-of-truth constraint, exact-head requirement, validation failure, or required final-report evidence.

## Bounded Parallel Work Options
- After the current requested task reaches a verified safe handoff or terminal disposition, and current canonical backlog evidence shows useful independent work exists, the completion response may offer a bounded continuation choice instead of only one unrelated next issue. The concise choices are: work on 5 other eligible issues, work on 10 other eligible issues, continue only the current lineage, or stop. If fewer than the named count are currently eligible, say "up to" the proven count rather than padding with blocked, stale, duplicate, or invented work.
- The option is discovery plus bounded authorization UX, not background execution. Do not begin unrelated work before the owner selects an offered batch unless the already-current mission explicitly authorized that batch. Once selected, freeze the original finite population from fresh open-issue evidence and reuse the existing bounded bug-work and finite-mission continuation contracts; do not silently expand to newly found issues or the whole backlog.
- Candidate selection must preserve each issue's canonical readiness, ownership, source of truth, authorization, external-write boundary, dependency state, active PR/branch/checkpoint/lease lineage, and bounded scope. Exclude blocked, stale, duplicate-owner/duplicate-lineage, already-active, or materially conflicting candidates instead of guessing. File/path overlap that would make independent PRs unsafe is a conflict unless the existing governed coordination path proves otherwise.
- Parallel work preserves one issue -> one scoped PR unless canonical ownership explicitly requires a different lineage. Each selected identity is reconciled exactly once with a terminal finite-campaign disposition such as completed/delivered, blocked-item-local, excluded, or shared-blocked. One item-local blocker never stops independent later items; a shared authorization, source-of-truth, capability, or material-decision blocker may stop the remaining population under the existing mission rules.
- The offered choice and its selection create no merge, issue-closure, workflow/protected-setting, credential, production, governed-field, or external-write authority. Presentation never weakens Safe Implementation Lane admission, exact-head validation, issue-local write authorization, or #3485 continuation/terminal-stop semantics.

## Historical Issue Recommendations And Actionability
- Before presenting a GitHub issue as the next actionable work target, reacquire its canonical current lifecycle state. Conversation memory, old issue sequences, labels, and historical handoffs are context, not current actionability evidence.
- In issue sequences, causal explanations, roadmaps, and next-work recommendations, explicitly mark closed/completed issues as **historical/completed**. They may explain lineage or prior fixes but must never appear as current work instructions merely because their subject remains relevant.
- Recommend a successor only after verifying that its exact issue or PR lineage is currently open and actionable under the existing readiness, authorization, ownership, and currentness contracts. If no such successor is proven, state that no current actionable target has been established; do not reopen or implicitly revive a historical issue.
- A direct request to work on a closed/completed issue follows the existing `AGENTS.md` historical-target continuation contract. Classification alone does not end the mission, and presentation never grants new mutation authority.

## Progress And Evidence Rules
- Render progress from named canonical states and evidence. Never persist a parallel progress record, workflow-state engine, or conversation-state service.
- Label a material progress claim `verified`, `inferred`, `proposed`, `blocked`, or `completed`.
- Reject percentages unless a canonical contract supplies the completion signal.
- Conversation memory may carry target identifiers but never overrides live canonical evidence.
- Presentation never implies execution authority, and a recommendation is never reported as executed.

## Version
0.2.2
