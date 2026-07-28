# GitHub Change Request
Use this template when a non-GitHub agent needs repository changes.

## Goal
Describe the intended repository change and why it is needed.

## Requesting Agent
Name the agent requesting the change and its overlay.

## Target Repository
Repository owner/name and target base branch.

## Authorization Route
Choose one:
- exact-file GitHub Change Request; or
- eligible Safe Implementation Lane under
  `01_Shared_Standards/github/safe-implementation-lane.md`.

For the safe lane, identify the open Tier 0 or Tier 1 `status:ready` issue,
GitHub source of truth, `no-external-write` boundary, repository-owner
implementation instruction, and confirmation that Tier 2 or excluded surfaces
do not apply.

## Target Files Or Bounded Scope Envelope
List exact files, or name the bounded module or repository area. For the Safe
Implementation Lane, include directly corresponding tests and documentation,
minimum public exports only when required by the objective, architecture
registration required by existing tests, and policy-required generated manifests
or changelog entries.

Every support file must be directly necessary, behaviorally subordinate, and
reported in the pull request. Material architecture, ownership, schema,
compatibility, workflow, credential, persistence, protected-setting, production,
or external-effect changes require a new decision.

## Proposed Content Or Patch
Paste the exact proposed content, patch, or implementation instructions.

## Branch Handling
Use a non-protected branch. A harness- or environment-assigned branch name is
acceptable when linked to the issue and used consistently; a preferred name is
not an authorization boundary.

## Acceptance Criteria
- Expected files exist or are updated.
- Existing source-of-truth rules remain intact.
- Shared rules stay in shared standards.
- Agent-specific rules stay in overlays.
- Registry ownership and routing stay in registry files.
- Required exact-head validation passes.
- No blocker or blocking review conversation remains before Ready-for-Review.

## Risks
List data, permission, governance, validation, duplication, compatibility, and
scope-envelope risks.

## Permissions Needed
State whether GitHub write access is required and identify the authorizing issue
or owner instruction. Readiness alone is evidence, not authorization.

Safe-lane authorization may include one non-protected branch, bounded
implementation, corresponding offline tests and docs, one draft PR, and
Ready-for-Review after validation. Merge, auto-merge, issue closure, protected
settings, workflows, credentials, governed fields, production, external writes,
source-of-truth changes, and irreversible actions remain separately authorized.

If authorization is unclear, the GitHub Service Agent must stop.

## Reviewer Or Owner
Name the responsible owner, reviewer, or approving agent.

## Stop Conditions
Stop when target repo, durable objective, bounded scope, owner, source of truth,
permission, or acceptance criteria are unclear, or when a material excluded
surface enters scope. Do not stop solely for a directly corresponding test,
mechanical registration, policy-required changelog entry, or an
environment-assigned non-protected branch allowed by the safe lane.

## Final Report Requirements
The GitHub Service Agent final report must include:
- branch and exact SHAs
- pull request link and state
- files changed, including why each support file was necessary
- tests run and exact-head evidence
- docs updated
- unresolved blockers
- handoff recommendations
- remaining risks
- rollback
- confirmation that merge and excluded surfaces remain unauthorized
