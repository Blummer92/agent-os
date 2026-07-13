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

## Review Rules

- Do not add new exceptions for routine docs.
- Prefer splitting active standards into index plus detail files.
- Archive exceptions should preserve historical content.
- Tooling-doc exceptions should be paired with later cleanup if used by agents.
- Remove exceptions after the file is brought under the limit.

## Version

0.1.0

## Changelog

- 0.1.0 initial exception policy for Issue #62.