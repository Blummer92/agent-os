# Agent Output Schema Compatibility Reference

The canonical Agent OS interaction-output contract is:

`01_Shared_Standards/global-engineering/agent-interaction-output-standard.md`

This file is test-facing compatibility guidance only. It must not define a
separate policy source or presentation order.

## Required Output Keys

Every governance-gated report must preserve these keys in a clearly marked
"Output Summary" machine-checkable/report evidence section when that summary is
required by the governing task:

```json
{
  "status": "domain-owned status value",
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
validated only when the corresponding profile is active. Visible prose may omit
empty or irrelevant fields; the Output Summary evidence remains separate from
profile-specific visible ordering.

## Compatibility Rules

1. Output Summary evidence includes all canonical base keys.
2. Array-valued fields remain arrays even when empty.
3. `status` is a canonical base evidence field; its scoped values and validation
   semantics remain owned by the applicable domain or operational contract.
4. Visible prose may omit empty or irrelevant fields when the presentation
   profile allows it.
5. Tests must not require every profile to display every field.
6. Presentation must not create or widen authorization.

## Profile Validation

Use `chatgpt-orchestrator.tests.md` for the canonical ten-profile presentation
matrix and `common-test-checklist.md` for shared compliance checks.
