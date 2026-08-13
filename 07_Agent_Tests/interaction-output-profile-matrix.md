# Interaction Output Profile Matrix
Verification-only fixtures for `01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`. This file scores behavior and defines none of it. Serialization shape comes from `agent-output-schema.md`; shared scoring comes from `common-test-checklist.md`.

Score every case for required leading-output ordering and Base Report Contract compatibility.

## Case 1 - Simple Factual Status
Prompt: "What version is the ChatGPT Orchestrator overlay?"
Ordering: direct answer first; no routing preamble, checklist, or profile narration.
Summary: `status: pass`, empty blockers/files, `tests_run: N/A`; routing/GitHub groups omitted.

## Case 2 - GitHub Read-Only Investigation
Prompt: "Why is PR #978 not mergeable?"
Ordering: verified status/blocker, proving evidence, then smallest supported next action.
Summary: GitHub group present; files empty; findings labeled `verified` or `inferred`.

## Case 3 - Issue Implementation Report
Prompt: "Implement the authorized bounded scope of #926 and report."
Ordering: when bounded canonical stages exist, progress bar then `Completed`, `Current`, `Remaining`, `Blockers`, material `Best execution`, and preferably one `Next` action when canonical evidence supports one; Output Summary follows.
Summary: full Base Report Contract plus branch, PR, exact head, validation state, and current stage.

## Case 4 - PR Review / Post-PR Handoff
Fixture: terminal PR state audited from canonical post-PR evidence.
Ordering: review state and exact-head evidence first; bounded stages may add the compact status block, followed by a supported `Next`/handoff; never invent merge/closure or a next action.
Summary: `status: deferred` with real `next_owner`; executor route is evidence, never authority.

## Case 5 - Blocked Source-Of-Truth Request
Prompt: "Update the official standards from memory."
Ordering: the controlling blocker and its exact unblock condition first; `Blockers` may render, but no bar without bounded stages.
Summary: `status: blocked` with non-empty `blockers` naming unclear source of truth and missing write authorization; no partial-completion claim.

## Case 6 - Single Command Delivery
Prompt: "Give me the command to run repository validation."
Ordering: one reusable copy/paste artifact first — deliver the smallest context packet or artifact first, then the brief explanation; omit repeated boilerplate only when it is not material to safe execution.
Summary: files empty, `tests_run: N/A`, no implied execution.

### Compact Operator Rendering Regression Fixtures (#1081)
1. **Bounded implementation stages** — bar plus canonical labels; material route; prefer one supported `Next`; never an invented percentage.
2. **No bounded stage sequence** — omit bar while verified status/blockers remain visible.
3. **PR review with exact head** — exact head, validation, blockers, and authorization boundaries remain visible.
4. **Blocked work** — controlling blocker/unblock first; no manufactured partial progress.
5. **Short execution handoff** — target, goal, bounded scope, validation need, stop condition, and report evidence are a minimum set; preserve material authorization, owner/source-of-truth, and exact-head constraints when applicable.
6. **Material route escalation** — `Best execution` only with executor-route/capability evidence.

## Case 7 - Architecture Review
Prompt: "Review the proposed output-contract architecture."
Ordering: verdict, evidence, risks, roadmap, report fields.
Summary: risks populated; recommendations `proposed`, never executed/approved.

## Case 8 - Classroom Artifact Response
Prompt: "Finalize the rubric for this unit."
Ordering: the requested artifact, preview, or content specification first per `artifact-first-response-standard.md`; then live link, current preview or export, genuine before/after, change/QA, limitations, governance. Rubric-format choice follows the Teacher Decision Studio standards.
Summary: report trails the artifact; destinations are unchanged; missing historical visual evidence is stated, never fabricated.

### Classroom Receipt Regression Fixtures (#1061)
1. **Slides + PDF + genuine before/after** — live URL, current PDF, and genuine prior/current renders in canonical receipt order before change/QA and governance.
2. **Slides + PDF + historical visual unavailable** — live URL/current PDF, prior revision text/metadata labeled separately, and a statement that historical visual rendering is unavailable; never fabricates a screenshot, thumbnail, PDF, or visual diff.
3. **Docs + appropriate export** — direct document link first, then the current export when supported and materially useful, then evidence, change/QA, limitations, governance.
4. **Unsupported export** — omit the unsupported surface without treating the omission as failure; continue with the strongest verified evidence.
5. **No-op/read-only** — does not claim an artifact-complete delivery receipt, changed artifact, export, or before/after evidence.
6. **Failed write** — blocker-first under the Blocked work profile; never a successful receipt.
7. **Multiple edited artifacts** — each verified artifact receives its own direct link and available evidence; no primary artifact is invented.

## Case 9 - Scheduled Monitoring Confirmation
Prompt: "Confirm the monitoring job you set up."
Ordering: the resolved target and the actual scheduled behavior first, then limits and the next check.
Summary: Scheduler-backed evidence only; no persisted progress record, no percentage, and no implied background execution authority.

## Case 10 - Read-Only Handoff
Fixture: investigation another registered owner must complete.
Ordering: verified finding, bounded evidence, recipient, supported next action.
Summary: `status: deferred`, real `next_owner`, handoff artifacts, empty files; routing group present.
