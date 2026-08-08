# Agent Output Schema Compatibility Reference

The canonical Agent OS interaction-output contract is:

`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`

This file is test-facing compatibility guidance only. It must not define a
separate policy source or presentation order.

## Base Evidence Keys

Governance-gated report evidence should expose the canonical base fields:

```json
{
  "status": "pass|fail|blocked|deferred",
  "blockers": [],
  "checks_passed": [],
  "checks_failed": [],
  "next_owner": "None",
  "handoff_artifacts": [],
  "files_changed": [],
  "tests_run": "N/A",
  "docs_updated": [],
  "remaining_risks": []
}
```

Profile-specific routing or GitHub implementation fields are conditional and are
validated only when the corresponding profile is active.

## Compatibility Rules

1. Base report evidence includes all canonical base keys.
2. Array-valued fields remain arrays even when empty.
3. `status` remains one of `pass`, `fail`, `blocked`, or `deferred`.
4. `deferred` requires a real `next_owner`.
5. `blocked` requires at least one blocker.
6. Visible prose may omit empty or irrelevant fields when the presentation
   profile allows it.
7. Tests must not require every profile to display every field.
8. Presentation must not create or widen authorization.

## Profile Validation

Use `chatgpt-orchestrator.tests.md` for the canonical ten-profile presentation
matrix and `common-test-checklist.md` for shared compliance checks.
