# Workflow Pipeline Issue Plan

## Status

Draft planning document. No issues have been created from this plan yet.

## Purpose

Plan the GitHub issue pipeline for building the Agent OS Workflow Pipeline in small, safe stages.

This plan does not implement code, modify the Workflow Scheduler, create GitHub Actions, create production automation, merge pull requests, or write to Notion, Drive, Sheets, or memory.

## Current State

- PR #141 defines `WF-001 — Idea Intake Workflow` as a narrow draft workflow.
- WF-001 has one responsibility: classify an idea and decide the next workflow.
- WF-001 smoke tests exist as a draft 10-test suite.
- WF-001 is not validated, schedulable, or operational.

## Desired Workflow Pipeline

| Workflow | Purpose | Status Target |
|---|---|---|
| WF-001 — Idea Intake | Classify one idea and recommend the next workflow. | Draft → Testable → Validated |
| WF-002 — Research Planning | Decide what research is needed and where to look. | Draft |
| WF-003 — MVP Planning | Define smallest useful implementation and non-goals. | Draft |
| WF-004 — Backlog / Issue Planning | Draft epics, issues, dependencies, and owners. | Draft |
| WF-005 — Testing Planning | Draft smoke tests, extended tests, and acceptance criteria. | Draft |
| WF-006 — GitHub Issue Creation Handoff | Prepare explicitly approved issue creation handoff. | Draft |

## MVP Boundary

The first MVP is **WF-001 only**.

WF-001 is complete only when:

1. The narrowed specification is reviewed.
2. The 10-test smoke suite is reviewed.
3. The 10-test smoke suite passes in a manual dry run.
4. The workflow remains classification-only.

## Stop Conditions

Stop if:

- workflow scope expands beyond one responsibility;
- issue creation is requested before WF-006 is specified;
- scheduler execution is requested before manual dry runs pass;
- workflow promotion is requested without smoke tests;
- source-of-truth, ownership, readiness, or authorization is unclear;
- any workflow tries to create or modify Notion, Drive, Sheets, memory, or production systems automatically.

## What Must Remain Manual

- Moving PR #141 out of draft.
- Merging PR #141.
- Creating GitHub issues from this plan.
- Promoting any workflow beyond Draft.
- Running manual dry runs until scheduler integration is approved.
- Any write to Notion, Drive, Sheets, memory, or production systems.

## Issue Sequence

### WFP-001 — Review and merge WF-001 Idea Intake specification

**Objective:** Review PR #141 and decide whether the narrowed WF-001 specification should merge.

**Why it matters:** WF-001 is the foundation for every later workflow. If the intake workflow is too broad, the whole pipeline will inherit scope creep.

**Acceptance criteria:**

- PR #141 remains documentation-only.
- WF-001 has one responsibility only.
- WF-001 stops after classification.
- WF-001 does not perform research, MVP planning, backlog planning, testing planning, implementation, or writes.
- Required final report fields are present in PR summary or review report.

**Dependencies:** None.

**Owner agent:** GitHub Service Agent.

**Estimated effort:** Small.

**Definition of done:** PR #141 is reviewed and either merged, revised, or rejected.

**Related workflow:** WF-001.

**Tests required:** Review against WF-001 scope rules.

**Blocked automation:** No automatic merge.

---

### WFP-002 — Run WF-001 10-test smoke suite

**Objective:** Manually run the 10 WF-001 smoke tests.

**Why it matters:** WF-001 must prove it can classify ideas without drifting into downstream work.

**Acceptance criteria:**

- All 10 tests are run.
- Results are recorded as PASS, FAIL, or BLOCKED.
- Any failure includes a short reason.
- WF-001 does not pass if it performs research, creates MVPs, drafts issues, creates tests, or writes anywhere.

**Dependencies:** WFP-001 specification review or draft approval to test.

**Owner agent:** QA / Test Agent.

**Estimated effort:** Small.

**Definition of done:** Smoke test report is posted to PR #141 or saved in a follow-up test report.

**Related workflow:** WF-001.

**Tests required:** `07_Agent_Tests/wf-001-idea-intake.tests.md`.

**Blocked automation:** No scheduler execution.

---

### WFP-003 — Revise WF-001 based on smoke-test failures

**Objective:** Make targeted changes to WF-001 only if smoke tests fail.

**Why it matters:** Failed tests should revise the smallest failing surface, not expand the workflow.

**Acceptance criteria:**

- Each revision maps to a failed or blocked smoke test.
- WF-001 remains classification-only.
- No downstream workflow content is added to WF-001.
- Updated tests pass or are explicitly marked unresolved.

**Dependencies:** WFP-002.

**Owner agent:** GitHub Service Agent, supported by QA / Test Agent.

**Estimated effort:** Small to Medium.

**Definition of done:** WF-001 is revised or failures are documented as accepted blockers.

**Related workflow:** WF-001.

**Tests required:** Re-run failed WF-001 smoke tests.

**Blocked automation:** No automatic promotion.

---

### WFP-004 — Define WF-002 Research Planning Workflow

**Objective:** Draft a narrow workflow that recommends research sources and open questions after WF-001 says an idea needs research.

**Why it matters:** Research should be planned before MVP decisions, especially when source authority or prior art is unclear.

**Acceptance criteria:**

- WF-002 has one responsibility: produce a Research Planning Report.
- WF-002 does not perform implementation.
- WF-002 does not create issues.
- WF-002 identifies internal and external sources to check.
- WF-002 includes source-context and live-verification boundaries.

**Dependencies:** WFP-001, WFP-002, WFP-003 if needed.

**Owner agent:** Integration Manager.

**Estimated effort:** Medium.

**Definition of done:** WF-002 draft spec exists with stop conditions and future scheduler mapping.

**Related workflow:** WF-002.

**Tests required:** 5-10 research-planning smoke tests.

**Blocked automation:** No live Notion or GitHub writes.

---

### WFP-005 — Define WF-003 MVP Planning Workflow

**Objective:** Draft a narrow workflow that turns a classified/researched idea into an MVP recommendation.

**Why it matters:** MVP scope must be decided before backlog or issue creation.

**Acceptance criteria:**

- WF-003 has one responsibility: produce an MVP Recommendation.
- WF-003 includes goals, non-goals, smallest useful implementation, success criteria, risks, and manual boundaries.
- WF-003 does not draft GitHub issues.
- WF-003 does not create tests beyond naming test needs.

**Dependencies:** WFP-004 or explicit decision that research is not needed.

**Owner agent:** ChatGPT Orchestrator.

**Estimated effort:** Medium.

**Definition of done:** WF-003 draft spec exists with smoke-test plan.

**Related workflow:** WF-003.

**Tests required:** 5-10 MVP-planning smoke tests.

**Blocked automation:** No issue creation, no PR creation, no scheduler execution.

---

### WFP-006 — Define WF-004 Backlog / Issue Planning Workflow

**Objective:** Draft a workflow that turns an approved MVP recommendation into GitHub-ready issue bodies.

**Why it matters:** Backlog planning should prepare issues without creating them automatically.

**Acceptance criteria:**

- WF-004 has one responsibility: prepare issue drafts.
- Each draft issue includes objective, why it matters, acceptance criteria, dependencies, owner, effort, definition of done, related workflow, tests required, and blocked automation.
- WF-004 does not create issues.
- WF-004 does not create milestones or labels.

**Dependencies:** WFP-005.

**Owner agent:** GitHub Service Agent.

**Estimated effort:** Medium.

**Definition of done:** WF-004 draft spec exists with issue body template.

**Related workflow:** WF-004.

**Tests required:** 5-10 issue-planning smoke tests.

**Blocked automation:** No automatic GitHub issue creation.

---

### WFP-007 — Define WF-005 Testing Planning Workflow

**Objective:** Draft a workflow that produces smoke tests, extended test categories, acceptance criteria, and manual run instructions.

**Why it matters:** Every workflow needs tests before promotion.

**Acceptance criteria:**

- WF-005 has one responsibility: prepare a Testing Recommendation.
- WF-005 separates smoke tests from extended test banks.
- WF-005 identifies critical blocker tests.
- WF-005 includes manual dry-run instructions.
- WF-005 does not run tests unless separately requested.

**Dependencies:** WFP-005 and WFP-006.

**Owner agent:** QA / Test Agent.

**Estimated effort:** Medium.

**Definition of done:** WF-005 draft spec exists with test planning output shape.

**Related workflow:** WF-005.

**Tests required:** 5-10 testing-planning smoke tests.

**Blocked automation:** No automated scheduler test execution.

---

### WFP-008 — Define WF-006 GitHub Issue Creation Handoff Workflow

**Objective:** Draft a workflow that prepares an explicit approval handoff for creating GitHub issues from approved issue drafts.

**Why it matters:** GitHub issue creation is a write action and should remain gated.

**Acceptance criteria:**

- WF-006 has one responsibility: prepare an issue-creation handoff.
- WF-006 requires explicit approval before issue creation.
- WF-006 verifies repository, issue count, issue bodies, labels, milestones, and owner.
- WF-006 does not create issues by default.
- WF-006 names the GitHub Service Agent as write owner.

**Dependencies:** WFP-006 and WFP-007.

**Owner agent:** GitHub Service Agent.

**Estimated effort:** Medium.

**Definition of done:** WF-006 draft spec exists with approval gate and handoff format.

**Related workflow:** WF-006.

**Tests required:** 5-10 handoff workflow smoke tests.

**Blocked automation:** No issue creation until approval.

---

### WFP-009 — Create workflow-pipeline registry

**Objective:** Draft a registry that lists workflow IDs, owners, maturity states, dependencies, and promotion status.

**Why it matters:** Once multiple workflows exist, Agent OS needs a single place to see the chain and avoid drift.

**Acceptance criteria:**

- Registry lists WF-001 through WF-006.
- Registry includes status, owner, dependency, source file, test file, and next promotion gate.
- Registry does not replace source-of-truth or responsibility-matrix rules.
- Registry starts as Draft.

**Dependencies:** At least WF-001 merged or accepted in draft.

**Owner agent:** Integration Manager, supported by GitHub Service Agent.

**Estimated effort:** Small to Medium.

**Definition of done:** Draft registry file exists and is referenced by workflow specs.

**Related workflow:** WF-001 through WF-006.

**Tests required:** Registry consistency review.

**Blocked automation:** No automatic routing changes.

---

### WFP-010 — Create manual dry-run packet for the full workflow chain

**Objective:** Prepare a dry-run packet for manually walking an idea through WF-001 through WF-006.

**Why it matters:** The full chain must be validated manually before scheduler execution.

**Acceptance criteria:**

- Packet includes input examples, expected outputs, stop conditions, and report templates.
- Packet includes at least three real Agent OS improvement ideas.
- Packet distinguishes manual dry run from scheduler execution.
- Packet includes pass/fail criteria.

**Dependencies:** WFP-004 through WFP-009.

**Owner agent:** QA / Test Agent.

**Estimated effort:** Medium.

**Definition of done:** Manual dry-run packet exists and is ready to use.

**Related workflow:** WF-001 through WF-006.

**Tests required:** Dry-run packet review.

**Blocked automation:** No scheduler run.

---

### WFP-011 — Run dry run on 3 real Agent OS improvement ideas

**Objective:** Manually run the full workflow chain on three real ideas.

**Why it matters:** The workflow chain should prove it handles real planning work before scheduler integration.

**Acceptance criteria:**

- Three real ideas are run through the manual chain.
- Each stage output is recorded.
- Failures are linked to workflow specs or tests.
- No writes occur without explicit approval.
- A recommendation is produced for each idea.

**Dependencies:** WFP-010.

**Owner agent:** QA / Test Agent.

**Estimated effort:** Medium to Large.

**Definition of done:** Dry-run report exists with pass/fail/blocker summary.

**Related workflow:** WF-001 through WF-006.

**Tests required:** Manual dry-run packet.

**Blocked automation:** No scheduler integration.

---

### WFP-012 — Decide whether workflow chain is ready for scheduler integration

**Objective:** Review evidence and decide whether the workflow chain should move toward scheduler integration.

**Why it matters:** Scheduler integration should be evidence-based, not assumed.

**Acceptance criteria:**

- WF-001 smoke tests have passed.
- Full-chain dry run has evidence from three ideas.
- Open blockers are documented.
- Decision is one of: Reject, Needs Revision, Needs More Dry Runs, Ready for Scheduler Integration Planning.
- No code changes are made as part of this issue.

**Dependencies:** WFP-011.

**Owner agent:** ChatGPT Orchestrator, supported by Integration Manager and QA / Test Agent.

**Estimated effort:** Small.

**Definition of done:** Decision report exists with next owner and next artifact.

**Related workflow:** WF-001 through WF-006.

**Tests required:** Evidence review.

**Blocked automation:** No scheduler implementation.

## Dependency Map

```text
WFP-001
  ↓
WFP-002
  ↓
WFP-003
  ↓
WFP-004
  ↓
WFP-005
  ↓
WFP-006
  ↓
WFP-007
  ↓
WFP-008
  ↓
WFP-009
  ↓
WFP-010
  ↓
WFP-011
  ↓
WFP-012
```

Parallel option after WFP-005:

```text
WFP-006 Backlog Planning and WFP-007 Testing Planning may be drafted in parallel after WF-003 is accepted, but they should not be validated independently until their handoff boundaries are clear.
```

## Smoke Test Map

| Workflow | Minimum Smoke Tests | Critical Risk Tested |
|---|---:|---|
| WF-001 | 10 | Classifies only; does not plan or write. |
| WF-002 | 5-10 | Recommends research without performing unauthorized writes. |
| WF-003 | 5-10 | Defines MVP without creating backlog or tests. |
| WF-004 | 5-10 | Drafts issue bodies without creating GitHub issues. |
| WF-005 | 5-10 | Drafts tests without running or promoting workflows. |
| WF-006 | 5-10 | Requires explicit approval before issue creation. |

## Promotion Criteria

| From | To | Requirement |
|---|---|---|
| Draft | Testable | Workflow spec exists and smoke tests exist. |
| Testable | Validated | Smoke tests pass in manual run. |
| Validated | Schedulable Candidate | Manual chain dry run succeeds with evidence. |
| Schedulable Candidate | Operational | Separate scheduler integration PR is approved and validated. |

## Recommended Next Issue To Start

Start with **WFP-001 — Review and merge WF-001 Idea Intake specification**.

Do not start WF-002 until WF-001 is reviewed and the 10-test smoke suite is ready for manual execution.

## Issue Creation Status

GitHub issue creation is intentionally **not performed** in this planning step.

Reason: GitHub does not have draft issues, and this plan should remain a reviewable backlog map until the user explicitly approves creation of the WFP issue set.
