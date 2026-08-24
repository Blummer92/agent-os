# Daily Agent Shortcuts

Use these shortcuts for common low-friction Agent OS work. They do not override
`00_Governance/write-authorization-policy.md`; they clarify safe daily lanes.

Canonical routing:

- risk tiers: `04_Registry/agent-risk-tiers.md`;
- lightweight or full intake: `03_Templates/prompts/agent-intake-form.md`;
- Tier 2, Tier 3, or governed work: `03_Templates/reports/live-readiness-checklist.md`.

## Daily Mode Rule

For read-only, local-only, planning, QA notes, routing, draft specs, and local
documentation tasks, complete Lightweight Intake and proceed when the boundary is
clear. Tier 0 and Tier 1 tasks should proceed without production-style gates while
they stay read-only or local-only.

Use Full Intake and Live Readiness for Tier 2 and Tier 3 work. Escalate when a
task touches external writes, production systems, governed fields, sharing or
permissions, source-of-truth records, sensitive data, or irreversible actions.
Ambiguous write authority fails closed to human decision.

## Dashboard Draft

Use ChatGPT Orchestrator with Dashboard Builder Overlay.
Mode: Tier 1 local spec only.
No canonical field writes.
Output: dashboard map plus governed-field notes.

## QA Review

Use QA / Test Agent.
Mode: Tier 0 read-only.
Output: pass/fail, evidence, risks, recommended next steps.

## Python Local Fix

Use GitHub Service Agent with `01_Shared_Standards/python/`.
Mode: Tier 1 local/repository engineering; any GitHub mutation still requires the
governed repository write path.
Output: files changed, tests run, limitations.

## Workspace Automation

Use ChatGPT Orchestrator with Google Workspace standards to classify the request.
Repository implementation routes to GitHub Service Agent. Live Workspace writes
require separate exact-target authorization and do not become authorized from a
legacy Workspace agent name.

## Instructional Material Draft

Use Instructional Materials Coach.
Mode: Tier 2 only if creating Drive copies.
Mode: Tier 1 if producing local YAML or local specs only.
Output: generated-content plan, missing inputs, and safety notes.
