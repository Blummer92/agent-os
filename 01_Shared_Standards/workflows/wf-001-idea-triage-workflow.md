# WF-001 — Idea Intake Workflow

## Status

Draft specification. Documentation only. Not schedulable yet.

## Purpose

Determine whether a new idea should continue into the Agent OS planning pipeline.

This workflow has one responsibility: classify one idea and recommend the next workflow. It stops after classification.

## Non-Goals

WF-001 does not:

- implement code
- modify the Workflow Scheduler
- create GitHub Actions
- create GitHub issues
- create milestones
- create pull requests
- create roadmap items
- generate an MVP
- perform research
- create tests
- write to GitHub, Notion, Google Drive, Sheets, memory, or production systems

## Inputs

Required:

- one improvement idea

Optional:

- supporting documents
- previous conversations
- GitHub issue
- GitHub PR
- Notion reference
- Google Drive reference

## Processing Questions

WF-001 answers exactly six questions.

### 1. Is this an Agent OS improvement?

Allowed values:

- Yes
- No
- Unknown

### 2. Has something similar already been proposed?

Allowed values:

- Yes
- No
- Unknown

### 3. Which system owns this idea?

Allowed values:

- GitHub
- Notion
- Google Drive
- Multiple
- Unknown

### 4. Which Agent OS agent should own the next step?

Return only the primary owner.

### 5. Estimate implementation complexity.

Allowed values:

- Small
- Medium
- Large

### 6. What should happen next?

Choose exactly one:

- Reject
- Needs Research
- Ready for MVP Planning
- Existing Work Found

## Output

Return exactly one report.

```text
Idea Classification Report

Idea:
Classification:
Primary Owner:
Source of Truth:
Complexity:
Duplicate Risk:
Recommended Next Workflow:
Recommendation:
```

## Stop Conditions

Stop immediately if:

- source of truth is unclear
- ownership is unclear
- authorization is unclear

Do not continue into research, MVP planning, backlog planning, testing, implementation, or writes.

## Future Scheduler Mapping

This workflow should map to the Workflow Scheduler as a single intake workflow with one primary task.

### Workflow Inputs

- improvement_idea
- optional_context
- optional_source_references

### Workflow Outputs

- idea_classification_report
- recommendation

### Workflow State

Recommended future states:

- draft
- intake_started
- classified
- stopped
- blocked

### Workflow Dependencies

WF-001 has no upstream workflow dependency.

Future downstream workflows may include:

- WF-002 Research Planning
- WF-003 MVP Planning
- WF-004 Backlog Planning
- WF-005 Testing Planning

### Approval Gates

No approval is required to classify an idea.

Approval is required before any downstream workflow creates or modifies repository, Notion, Drive, Sheets, memory, or production artifacts.

### Audit Events

Recommended future audit events:

- workflow_started
- idea_received
- idea_classified
- stop_condition_triggered
- workflow_completed

### Failure States

| Failure State | Meaning | Recovery |
|---|---|---|
| ambiguous_idea | The idea is not clear enough to classify. | Ask user to clarify. |
| unknown_source_of_truth | The owner system cannot be determined. | Stop and request source clarification. |
| unknown_owner | The responsible Agent OS owner cannot be determined. | Stop and request routing clarification. |
| missing_authorization | The next action would require an unapproved write. | Stop and request explicit approval. |

## Workflow Maturity

Current maturity: **Draft**.

Do not mark this workflow as Testable, Validated, Schedulable, or Operational until a separate smoke-test specification and manual dry run exist.

## Readiness For Workflow Scheduler Integration

Not ready for scheduler execution.

Ready only after:

1. Human review approves the narrowed scope.
2. WF-001 smoke tests are created.
3. Manual dry runs succeed on real Agent OS improvement ideas.
4. Ownership and stop conditions are confirmed.
