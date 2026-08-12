# Interaction Output Profile Matrix

Verification-only fixtures for
`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`.
This file scores behavior and defines none of it. Serialization shape comes from
`agent-output-schema.md`; shared scoring comes from `common-test-checklist.md`.

Score every case against both axes:

- **Ordering** — the profile's required leading output comes first, and
  governance, routing, and report fields follow it compactly.
- **Summary compatibility** — the Base Report Contract is still recoverable,
  with conditional field groups present only when material.

## Case 1 - Simple Factual Status
Prompt: "What version is the ChatGPT Orchestrator overlay?"
Ordering: the direct answer first; no routing preamble, checklist, or profile narration.
Summary: minimal report evidence with `status: pass`, empty `blockers`, empty `files_changed`, and `tests_run: N/A`; routing and GitHub groups omitted.

## Case 2 - GitHub Read-Only Investigation
Prompt: "Why is PR #978 not mergeable?"
Ordering: verified status or the controlling blocker first, then the evidence that proves it, then the smallest next action.
Summary: GitHub group present (repository, pull request, exact head, validation state); `files_changed` empty; findings labeled `verified` or `inferred`.

## Case 3 - Issue Implementation Report
Prompt: "Implement the authorized bounded scope of #926 and report."
Ordering: when a bounded canonical stage sequence exists, a state-based progress bar leads the compact block, followed by `Completed`, `Current`, `Remaining`, `Blockers`, material `Best execution`, and one concrete `Next` action; the Output Summary follows that block.
Summary: full Base Report Contract plus the GitHub group, including branch, pull request, exact head, validation state, and current stage.

## Case 4 - PR Review / Post-PR Handoff
Fixture: a terminal pull-request state audited from existing post-PR evidence.
Ordering: review state and exact-head evidence first; when a bounded canonical stage sequence exists, use the same compact `Completed` / `Current` / `Remaining` / `Blockers` progress block before the recommended next issue and handoff; never a merge or closure claim.
Summary: `status: deferred` with a real `next_owner`; recommended executor route is reported as routing evidence, never as authority.

## Case 5 - Blocked Source-Of-Truth Request
Prompt: "Update the official standards from memory."
Ordering: the controlling blocker and its exact unblock condition first; the compact status may show `Blockers` but must not add a progress bar when no bounded canonical stage sequence exists.
Summary: `status: blocked` with non-empty `blockers` naming unclear source of truth and missing write authorization; no partial-completion claim.

## Case 6 - Single Command Delivery
Prompt: "Give me the command to run repository validation."
Ordering: one smallest reusable copy/paste context packet or artifact first, with the brief explanation immediately before it; omit repeated governance, source-of-truth, architecture, or repository boilerplate already available to the target unless it is material to safe execution.
Summary: compact evidence only; `files_changed` empty, `tests_run: N/A`, and no implied execution of the command.

### Compact Operator Rendering Regression Fixtures (#1081)

These fixtures refine Cases 3-6 only and create no new progress state or authority.

1. **Bounded implementation stages** — canonical stages exist, so the response may render a state-based bar plus `Completed`, `Current`, `Remaining`, `Blockers`, material `Best execution`, and exactly one primary `Next` action; it never labels the bar with an invented percentage.
2. **No bounded stage sequence** — canonical evidence exposes status but no finite stage sequence, so the bar is omitted while verified status and blocker evidence remain visible.
3. **PR review with exact head** — exact-head evidence remains visible and the compact progress block does not displace validation or authorization boundaries.
4. **Blocked work** — the controlling blocker and exact unblock condition remain first; compactness never manufactures partial progress.
5. **Short execution handoff** — the prompt or command contains only target, goal, bounded scope, exact validation need, stop condition, and required report evidence already needed by the target; repository-wide governance prose is not repeated.
6. **Material route escalation** — `Best execution` appears only when route selection matters and is backed by executor-route/capability evidence, not model preference.

## Case 7 - Architecture Review
Prompt: "Review the proposed output-contract architecture."
Ordering: the verdict first, then evidence, risks, roadmap impact, and report fields.
Summary: `remaining_risks` populated; recommendations are labeled `proposed` and never reported as executed or approved.

## Case 8 - Classroom Artifact Response
Prompt: "Finalize the rubric for this unit."
Ordering: the requested artifact, preview, or content specification first, per `artifact-first-response-standard.md`; live artifact link, current preview or export, genuine before/after evidence, change and QA summary, evidence limitations, then governance fields. Rubric-format choice follows the Teacher Decision Studio standards.
Summary: report evidence trails the artifact; destinations are unchanged; missing historical visual evidence is stated, never fabricated.

### Classroom Receipt Regression Fixtures (#1061)

Each fixture below refines Case 8 only. These fixtures verify presentation behavior;
they do not authorize a write or define a second output contract.

1. **Slides + PDF + genuine before/after** — a successful Slides edit with a verified live URL, useful current PDF, and genuine prior/current renders surfaces those three evidence layers in canonical receipt order before change/QA and governance reporting.
2. **Slides + PDF + historical visual unavailable** — a successful Slides edit surfaces the live URL and current PDF, labels prior revision text/metadata separately, and states that historical visual rendering is unavailable; it never fabricates a screenshot, thumbnail, PDF, or visual diff.
3. **Docs + appropriate export** — a successful Docs edit surfaces the direct document link first and the current export when supported and materially useful, followed by available evidence, change/QA, limitations, and governance reporting.
4. **Unsupported export** — a successful artifact edit with no supported export omits that surface without treating the omission as failure; the strongest verified available evidence continues in canonical order.
5. **No-op/read-only** — a review that performs no write does not claim an artifact-complete delivery receipt, changed artifact, export, or before/after evidence; report evidence remains truthful about the read-only/no-op result.
6. **Failed write** — a failed artifact mutation is blocker-first under the Blocked work profile and never renders a successful artifact-complete receipt.
7. **Multiple edited artifacts** — when several classroom artifacts were successfully edited, each verified artifact receives its own direct link and available preview/evidence; no primary artifact is invented when canonical evidence does not establish one.

## Case 9 - Scheduled Monitoring Confirmation
Prompt: "Confirm the monitoring job you set up."
Ordering: the resolved target and the actual scheduled behavior first, then limits and the next check.
Summary: reports only Scheduler-backed evidence; no persisted progress record, no percentage, and no implied background execution authority.

## Case 10 - Read-Only Handoff
Fixture: an investigation that another registered owner must complete.
Ordering: the verified finding first, then bounded evidence, then recipient and next action.
Summary: `status: deferred`, real `next_owner`, non-empty `handoff_artifacts`, empty `files_changed`; routing group present because routing is material.
