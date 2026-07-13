# GitHub Change Request

Use this template when a non-GitHub agent needs repository changes.

## Goal

Describe the intended repository change and why it is needed.

## Requesting Agent

Name the agent requesting the change and its overlay.

## Target Repository

Repository owner/name and target base branch.

## Target Files

List files to add, edit, move, or remove.

## Proposed Content Or Patch

Paste the exact proposed content, patch, or implementation instructions.

## Acceptance Criteria

- Expected files exist or are updated.
- Existing source-of-truth rules remain intact.
- Shared rules stay in shared standards.
- Agent-specific rules stay in overlays.
- Registry ownership and routing stay in registry files.

## Risks

List data, permission, governance, validation, or duplication risks.

## Permissions Needed

State whether GitHub write access is required.

If authorization is unclear, the GitHub Service Agent must stop.

## Reviewer Or Owner

Name the responsible owner, reviewer, or approving agent.

## Stop Conditions

Stop when target repo, file scope, owner, source of truth, permission, or
acceptance criteria are unclear.

## Final Report Requirements

The GitHub Service Agent final report must include:

- branch
- pull request link
- files changed
- tests run
- docs updated
- unresolved blockers
- handoff recommendations
- remaining risks