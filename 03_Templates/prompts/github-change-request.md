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

For an exact-file request, bind the authenticated owner instruction to the
repository, base and source preimages, exact paths and intended change,
and the specific permitted operations. An existing issue may be a non-closing
coordination reference without being the primary implementation issue. If the
request makes a primary issue claim, the existing primary-PR creation admission
still applies; otherwise do not invoke it with a substitute issue or create an
administrative issue.

Before writing, verify current scope and authority, exact repository/base and
preimages, applicable initial CKR6, and current competing-work evidence.
Immediately before Draft creation, verify canonical branch/head and PR evidence
against the approved request and changes. Reuse a single matching Draft only
within the same authorized lineage; reconcile uncertain writes before any retry.
Stop for incomplete evidence, competing or ambiguous work, or changed scope.
Keep any genuinely applicable checkpoint or lease checks; GitHub PR search
alone is not lease clearance. Preserve exact canonical Draft readback and
existing validation and independent QA. Obtain any required PR/head-bound CKR6
result only after canonical observation of that head; it does not substitute
for initial preflight or authorize landing.

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

## Pattern + Docs Freshness Gate
State the existing pattern checked (`none found` allowed), reusable capability registry relevance (`not applicable` allowed), canonical implementation path, proving tests/behavior, docs expected to change, docs intentionally unchanged with bounded reason, and changelog/module-version/registry review.
`Docs intentionally unchanged because...` is valid only when public behavior, public interfaces, workflows, owner expectations, standards, templates, and reusable capability records are unchanged.

## Proposed Content Or Patch
Paste the exact proposed content, patch, or implementation instructions.

## Branch Handling
Use a non-protected branch. A harness- or environment-assigned branch name is
acceptable when bound to the authorized request or implementation issue and
used consistently; a preferred name is not an authorization boundary.

## Acceptance Criteria
- Expected files exist or are updated.
- Existing source-of-truth rules remain intact.
- Shared rules stay in shared standards.
- Agent-specific rules stay in overlays.
- Registry ownership and routing stay in registry files.
- Pattern + Docs Freshness Gate is completed or explicitly marked not applicable
  with a bounded reason.
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
