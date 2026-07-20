# Agent Risk Tiers

## Purpose

Define the canonical daily-use risk model for Agent OS. The tier describes the
highest-risk write surface in a task; it does not grant authorization.

## Tiers

| Tier | Typical work | Intake | Required boundary |
|---|---|---|---|
| 0 — Read-only reviewer | Review, analysis, routing, QA evidence, planning | Lightweight intake | No writes or state changes |
| 1 — Local builder | Local files, local drafts, fixtures, non-authoritative specs | Lightweight intake | No external, governed, or production write |
| 2 — External draft or copy creator | Draft email, Drive copy, external draft record, proposed governed change | Full intake and explicit target approval | Draft/copy only unless separately authorized |
| 3 — Production modifier | Canonical records, permissions, sharing, production data, deployment, irreversible action | Full intake, live readiness, and explicit owner approval | Exact target, rollback, validation, and audit evidence |

## Classification Rules

- Classify the whole task at the highest applicable tier.
- Read-only access to sensitive or private data may require additional handling even
  when the action itself is Tier 0.
- A local artifact becomes Tier 2 when it is copied, published, sent, uploaded, or
  written to an external system.
- Any change to governed fields, source-of-truth records, permissions, sharing,
  production systems, or irreversible artifacts is Tier 2 or Tier 3.
- Validation, readiness, capability, labels, or a passing test never lower the tier
  or create authorization.

## Intake Routing

### Lightweight intake

Allowed for Tier 0 and Tier 1 when the target, owner, source of truth, and local-only
boundary are clear. Confirm scope, expected output, and prohibited write surfaces.

### Full intake and live readiness

Required for Tier 2 and Tier 3. Confirm:

- exact target and system of record;
- field or artifact owner;
- allowed write surface;
- required human approval;
- validation and rollback;
- audit or handoff destination;
- stop conditions.

## Escalation

Escalate immediately when scope expands, authorization becomes ambiguous, a local
artifact is about to leave the local environment, or a task touches production,
governed data, source-of-truth records, permissions, sharing, or irreversible state.

## Daily Mode

`03_Templates/prompts/daily-agent-shortcuts.md` provides examples for low-friction
work. Those shortcuts use this registry and do not override
`00_Governance/write-authorization-policy.md`.

## Ownership

The Integration Manager owns tier definitions and routing. The system owner retains
approval authority for governed or production writes. The GitHub Service Agent owns
approved repository changes.

## Version

0.1.0
