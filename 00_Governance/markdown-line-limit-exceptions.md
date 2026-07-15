# Markdown Line Limit Exceptions

## Purpose

This file lists approved exceptions to the under-100-line Markdown rule used by
`07_Agent_Tests/validate-repo-structure.sh`.

Exceptions must be explicit, narrow, and reviewed. New active Agent OS guidance
should still be split into files under 100 lines unless a governance review
approves an exception.

## Current Exceptions

These files predate the line-limit enforcement cleanup and are exempt until they
are split, summarized, or replaced by smaller indexed documents.

```text
01_Shared_Standards/python/integration-testing-standard.md
01_Shared_Standards/python/test-environment-setup.md
01_Shared_Standards/python/unit-testing-standard.md
01_Shared_Standards/python/testing-standard.md
06_Archive/workflow-scheduler-planning/PART_A_TO_PART_B_HANDOFF.md
06_Archive/workflow-scheduler-planning/PART_A_FINAL_SUMMARY.md
06_Archive/workflow-scheduler-planning/PHASE_B_SCOPE.md
08_Tooling/workflow-scheduler/docs/ADAPTER_CONTRACT_FUTURE.md
08_Tooling/workflow-scheduler/docs/API_REFERENCE.md
08_Tooling/workflow-scheduler/docs/USER_GUIDE.md
08_Tooling/workflow-scheduler/docs/ARCHITECTURE.md
07_Agent_Tests/agent-output-schema.md
```

## High-Risk Governed Exceptions (Deferred)

These files are active, high-risk governed documents. They are not being split
or shortened during the current line-limit cleanup sequence because doing so
opportunistically would risk conflicting with pending governed work. These
exceptions are temporary and reviewable, not a permanent allowance for
unlimited growth.

### Navigation stack (deferred pending Issue #97)

```text
01_Shared_Standards/navigation/navigation-registry-architecture.md
01_Shared_Standards/navigation/navigation-registry-data-model.md
01_Shared_Standards/navigation/connector-adapter-framework.md
01_Shared_Standards/navigation/notion-smoke-test-target-approval-handoff.md
01_Shared_Standards/navigation/notion-read-only-connector-pilot-plan.md
01_Shared_Standards/navigation/notion-live-access-approval-plan.md
01_Shared_Standards/navigation/workspace-discovery-service.md
```

These 7 files are directly tied to pending Issue #97 Navigation Registry
planning and should not be opportunistically restructured before that work
decides the correct shape. Remove or revise this exception when Issue #97
restructures or formally accepts the navigation standards.

### Governance v1.0 baseline (deferred pending governance review)

```text
00_Governance/agent-os-governance-v1-baseline.md
```

This is the canonical Governance v1.0 baseline and should only be split or
shortened under a dedicated governance review, not as part of routine
line-limit cleanup. Remove or revise this exception after a dedicated
governance-baseline review.

## Review Rules

- Do not add new exceptions for routine docs.
- Prefer splitting active standards into index plus detail files.
- Archive exceptions should preserve historical content.
- Tooling-doc exceptions should be paired with later cleanup if used by agents.
- Remove exceptions after the file is brought under the limit.
- High-risk governed exceptions must state a review trigger and are not
  permanent.

## Version

0.2.0

## Changelog

- 0.2.0 added 8 high-risk governed exceptions (the Issue #97 navigation stack
  and the Governance v1.0 baseline) for PR C of the Markdown line-limit
  cleanup sequence; each has a stated review trigger and is temporary.
- 0.1.0 initial exception policy for Issue #62.