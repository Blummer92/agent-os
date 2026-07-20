# Daily Agent Shortcuts

Use these shortcuts for common low-friction agent work. They operate under
`00_Governance/agent-os-advisory-mode.md` during pilot review and do not override
`00_Governance/write-authorization-policy.md`; they clarify safe daily lanes.

The canonical tier definitions and escalation rules live in
`04_Registry/agent-risk-tiers.md`.

## Daily Mode Rule

For read-only, local-only, planning, QA notes, routing, draft specs, and local
documentation tasks, proceed after lightweight intake.

Tier 0 and Tier 1 tasks should proceed without extra approval when they stay
read-only or local-only.

Use full intake and live-readiness review for Tier 2 and Tier 3 work. Escalate when
a task touches external writes, production systems, governed fields, sharing or
permissions, source-of-truth records, sensitive student/private data, or
irreversible actions.

## Dashboard Draft

Use Dashboard Builder Overlay.
Mode: Tier 1 local spec only.
No canonical field writes.
Output: dashboard map plus governed-field notes.

## QA Review

Use QA / Test Agent.
Mode: Tier 0 read-only.
Output: pass/fail, evidence, risks, recommended next steps.

## Python Local Fix

Use Python Development Overlay.
Mode: Tier 1 local files only.
Output: files changed, tests run, limitations.

## Instructional Material Draft

Use Instructional Materials Coach.
Mode: Tier 2 only if creating Drive copies.
Mode: Tier 1 if producing local YAML or local specs only.
Output: generated-content plan, missing inputs, and safety notes.
