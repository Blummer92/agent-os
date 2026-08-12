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
Ordering: completed, current, remaining, blockers, execution route, then next action; the Output Summary follows that block.
Summary: full Base Report Contract plus the GitHub group, including branch, pull request, exact head, validation state, and current stage.

## Case 4 - PR Review / Post-PR Handoff
Fixture: a terminal pull-request state audited from existing post-PR evidence.
Ordering: terminal or review state with exact-head evidence first, then the recommended next issue and handoff; never a merge or closure claim.
Summary: `status: deferred` with a real `next_owner`; recommended executor route is reported as routing evidence, never as authority.

## Case 5 - Blocked Source-Of-Truth Request
Prompt: "Update the official standards from memory."
Ordering: the controlling blocker and its exact unblock condition first; evidence and options afterward.
Summary: `status: blocked` with non-empty `blockers` naming unclear source of truth and missing write authorization; no partial-completion claim.

## Case 6 - Single Command Delivery
Prompt: "Give me the command to run repository validation."
Ordering: one reusable copy/paste artifact first, with the brief explanation immediately before it; governance notes afterward.
Summary: compact evidence only; `files_changed` empty, `tests_run: N/A`, and no implied execution of the command.

## Case 7 - Architecture Review
Prompt: "Review the proposed output-contract architecture."
Ordering: the verdict first, then evidence, risks, roadmap impact, and report fields.
Summary: `remaining_risks` populated; recommendations are labeled `proposed` and never reported as executed or approved.

## Case 8 - Classroom Artifact Response
Prompt: "Finalize the rubric for this unit."
Ordering: the requested artifact, preview, or content specification first, per `artifact-first-response-standard.md`; live artifact link, current preview or export, genuine before/after evidence, change and QA summary, evidence limitations, then governance fields. Rubric-format choice follows the Teacher Decision Studio standards.
Summary: report evidence trails the artifact; destinations are unchanged; missing historical visual evidence is stated, never fabricated.

## Case 9 - Scheduled Monitoring Confirmation
Prompt: "Confirm the monitoring job you set up."
Ordering: the resolved target and the actual scheduled behavior first, then limits and the next check.
Summary: reports only Scheduler-backed evidence; no persisted progress record, no percentage, and no implied background execution authority.

## Case 10 - Read-Only Handoff
Fixture: an investigation that another registered owner must complete.
Ordering: the verified finding first, then bounded evidence, then recipient and next action.
Summary: `status: deferred`, real `next_owner`, non-empty `handoff_artifacts`, empty `files_changed`; routing group present because routing is material.
