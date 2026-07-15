# WF-001 — Idea Triage Workflow

## Status

Draft specification. Documentation only. Not schedulable yet.

## Purpose

Define a reusable Workflow Scheduler-compatible planning workflow that turns one new Agent OS improvement idea into an implementation-ready planning packet, then stops before implementation.

This workflow is intended to become schedulable later without redesign, but this document does not modify the Workflow Scheduler, create executable YAML, create issues, create milestones, create pull requests, or write to Notion or Google Drive.

## Ownership And Routing

| Responsibility | Owner |
|---|---|
| Workflow specification ownership | GitHub Service Agent |
| Workflow execution architecture | Workflow Scheduler |
| Cross-system lookup routing | Integration Manager |
| Acceptance evidence | QA / Test Agent |
| Final implementation writes | GitHub Service Agent |

## Workflow Maturity

| State | Meaning |
|---|---|
| Draft | Workflow idea is documented but not validated. |
| Specified | Required stages, inputs, outputs, stops, and future scheduler fields are defined. |
| Testable | Smoke tests exist for the workflow behavior. |
| Validated | Smoke tests pass in manual or scheduled dry-run mode. |
| Schedulable | Ready to map into Workflow Scheduler YAML or native workflow definition. |
| Operational | Actively executed by the Workflow Scheduler with audit trail. |

Current maturity: **Draft**.

## Workflow Objective

Transform one new Agent OS improvement idea into a planning packet that answers:

1. What is the idea?
2. Is it an Agent OS improvement?
3. What already exists?
4. What is the smallest useful MVP?
5. What issues would be needed?
6. What tests would be needed?
7. Should implementation proceed?

## Inputs

Required:

- One Agent OS improvement idea.

Optional:

- Supporting documents.
- Prior conversation context.
- Related GitHub issues.
- Related GitHub pull requests.
- Related Notion references.
- Related Google Drive references.
- Existing roadmap references.

## Outputs

This workflow prepares, but does not create:

- Idea Classification Report.
- Research Packet Recommendation.
- MVP Recommendation.
- Backlog Recommendation.
- Smoke Test Recommendation.
- Extended Test Recommendation.
- Implementation Recommendation.

## Non-Goals

This workflow must not:

- Implement code.
- Modify Workflow Scheduler code or docs.
- Create GitHub Actions.
- Create GitHub issues automatically.
- Create milestones automatically.
- Create pull requests automatically.
- Write to Notion.
- Write to Google Drive.
- Change readiness, approval, audit, source-of-truth, ownership, or governed fields.
- Promote an experimental standard to stable.

## Stages

### Stage 1 — Idea Intake

Determine:

- Is this an Agent OS improvement?
- Is it governance, tooling, workflow, classroom, testing, infrastructure, response behavior, source routing, or automation?
- Does something similar already exist?
- Which system owns the idea?
- Which agent should own the next step?
- Is source of truth clear?

Return: **Idea Classification Report**.

Required fields:

```text
Idea:
Classification:
Primary owner:
Supporting agents:
Source of truth:
Existing related artifacts:
Potential risk level:
Recommended next stage:
```

### Stage 2 — Research Planning

Determine:

- Existing Agent OS documentation.
- Existing GitHub issues.
- Existing pull requests.
- Existing roadmap items.
- Existing registry entries.
- Existing Notion pages or cached Notion navigation records.
- Existing Google Drive artifacts, if relevant.
- External prior art, if needed.

Return: **Research Packet Recommendation**.

Required fields:

```text
Research needed:
Internal sources to check:
External examples to compare:
Source Context needed? yes/no
Live verification needed before implementation? yes/no
Open questions:
```

### Stage 3 — MVP Planning

Determine:

- Smallest useful implementation.
- Explicit non-goals.
- Required source-of-truth boundaries.
- Required human approval gates.
- Success criteria.
- Risks.
- What must remain manual.

Return: **MVP Recommendation**.

Required fields:

```text
MVP name:
Problem statement:
Smallest useful version:
Non-goals:
Success criteria:
Required approval gates:
Risks:
Recommended maturity target:
```

### Stage 4 — Backlog Planning

Recommend:

- Epics.
- Issues.
- Milestones.
- Dependencies.
- Owners.
- Handoff paths.

Do not create issues, labels, milestones, branches, or pull requests.

Return: **Backlog Recommendation**.

Required fields:

```text
Epics:
Draft issues:
Dependencies:
Owner agents:
Suggested milestone grouping:
Blocked until:
```

### Stage 5 — Testing Planning

Recommend:

- Smoke tests.
- Extended tests.
- Acceptance criteria.
- Critical blockers.
- Manual evaluation method.
- Future automation option.

Return: **Testing Recommendation**.

Required fields:

```text
Smoke tests:
Critical blocker tests:
Extended test categories:
Acceptance criteria:
Manual run instructions:
Future automation candidate? yes/no
```

### Stage 6 — Implementation Recommendation

Choose exactly one:

- Reject.
- Needs Research.
- Needs Revision.
- Ready for GitHub Planning.

Return: **Implementation Recommendation**.

Required fields:

```text
Recommendation:
Reason:
Next owner:
Next artifact:
Human approval needed? yes/no
```

## Stop Conditions

The workflow must stop if:

- Target system is unclear.
- Source of truth is unclear.
- Ownership is unclear.
- Authorization is unclear.
- The idea requires a write to GitHub, Notion, Drive, Sheets, memory, or another system without explicit approval.
- A readiness/status/source-of-truth/governed-field decision is requested without live verification.
- A proposed action would skip MVP definition or tests.
- A proposed action would implement before the planning packet is reviewed.

## Approval Gates

| Gate | Required Before | Approval Type |
|---|---|---|
| Gate 1 | Advancing from intake to research | Lightweight human confirmation if source or scope is unclear. |
| Gate 2 | Advancing from MVP recommendation to backlog generation | Human confirmation of MVP boundary. |
| Gate 3 | Creating any GitHub issue, PR, milestone, label, or branch | Explicit user approval and GitHub Service Agent execution. |
| Gate 4 | Writing to Notion, Drive, Sheets, or other external systems | Explicit user approval and correct owner/connector. |
| Gate 5 | Marking workflow Schedulable or Operational | Validated tests and governance review. |

## Future Scheduler Integration

This section is designed to map directly to the existing Workflow Scheduler model later.

### Proposed Workflow Metadata

```yaml
workflow_id: "wf-001-idea-triage"
title: "Idea Triage Workflow"
mode: "Draft"
created_by: "GitHub Service Agent"
```

### Proposed Task Graph

```yaml
tasks:
  - id: "idea-intake"
    type: "planning"
    owner: "ChatGPT Orchestrator"
    action: "classify_agent_os_improvement_idea"
    idempotency_key: "wf-001-idea-intake-{idea_hash}"
    priority: 5

  - id: "research-planning"
    type: "research"
    owner: "Integration Manager"
    action: "prepare_research_packet_recommendation"
    idempotency_key: "wf-001-research-{idea_hash}"
    depends_on: ["idea-intake"]
    priority: 4

  - id: "mvp-planning"
    type: "planning"
    owner: "ChatGPT Orchestrator"
    action: "prepare_mvp_recommendation"
    idempotency_key: "wf-001-mvp-{idea_hash}"
    depends_on: ["research-planning"]
    priority: 3

  - id: "backlog-planning"
    type: "planning"
    owner: "GitHub Service Agent"
    action: "draft_backlog_recommendation"
    idempotency_key: "wf-001-backlog-{idea_hash}"
    depends_on: ["mvp-planning"]
    priority: 2

  - id: "testing-planning"
    type: "qa"
    owner: "QA / Test Agent"
    action: "draft_testing_recommendation"
    idempotency_key: "wf-001-testing-{idea_hash}"
    depends_on: ["mvp-planning"]
    priority: 2

  - id: "implementation-recommendation"
    type: "decision"
    owner: "ChatGPT Orchestrator"
    action: "prepare_implementation_recommendation"
    idempotency_key: "wf-001-recommendation-{idea_hash}"
    depends_on: ["backlog-planning", "testing-planning"]
    approval_required: true
    priority: 1
```

### Workflow State

Recommended future states:

- draft.
- intake_complete.
- research_recommended.
- mvp_recommended.
- backlog_drafted.
- tests_drafted.
- approval_pending.
- ready_for_github_planning.
- rejected.
- blocked.

### Dependencies

- Research Planning depends on Idea Intake.
- MVP Planning depends on Research Planning.
- Backlog Planning depends on MVP Planning.
- Testing Planning depends on MVP Planning.
- Implementation Recommendation depends on both Backlog Planning and Testing Planning.

### Audit Events

Recommended future audit events:

- workflow_spec_loaded.
- idea_classified.
- research_recommendation_created.
- mvp_recommendation_created.
- backlog_recommendation_created.
- test_recommendation_created.
- approval_requested.
- approval_granted.
- approval_rejected.
- workflow_blocked.
- workflow_completed.

### Retry Behavior

- Retry only read-only lookup failures and transient adapter failures.
- Do not retry governance blocks automatically.
- Do not retry ambiguous target failures automatically.
- Do not retry source-of-truth conflicts automatically.
- Re-run after human clarification or approval.

### Failure States

| Failure State | Meaning | Recovery |
|---|---|---|
| ambiguous_target | The idea or target system is unclear. | Ask user to clarify. |
| missing_authorization | Requested next step needs approval. | Stop and request approval. |
| conflicting_source_of_truth | Source records disagree. | Escalate to Integration Manager. |
| insufficient_research | Internal or external examples are missing. | Return Needs Research. |
| mvp_too_large | MVP scope is too broad. | Return Needs Revision. |
| tests_missing | Smoke tests or acceptance criteria are missing. | Return Needs Revision. |

## Expected Final Packet Format

```text
# Idea Triage Packet

## Idea Classification

## Research Recommendation

## MVP Recommendation

## Backlog Recommendation

## Testing Recommendation

## Implementation Recommendation

## Approval Needed

## Required Final Report
- files changed
- docs updated
- tests run
- unresolved blockers
- handoff recommendations
- remaining risks
```

## Readiness For Scheduler Integration

Current status: **Not ready for scheduler execution**.

Ready only after:

1. This specification is reviewed.
2. Smoke tests are created.
3. A manual dry run succeeds on at least three real Agent OS improvement ideas.
4. Ownership and approval gates are confirmed.
5. A future implementation issue is approved.

## Remaining Open Questions

- Should WF-001 live as a shared standard, a workflow scheduler example, or a formal workflow registry entry once validated?
- Should the workflow create a planning packet file, a GitHub issue body, or both after approval?
- Which agent owns external prior-art research when web research is needed?
- Should Notion source discovery be required for every classroom-related improvement idea?
- What is the minimum passing smoke-test set before this can move from Draft to Testable?
