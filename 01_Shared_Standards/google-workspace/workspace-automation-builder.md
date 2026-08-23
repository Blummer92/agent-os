# Workspace Automation Builder

## Purpose

Use this shared standard when designing or building Google Workspace automations
for Drive, Docs, Sheets, Gmail, Calendar, Apps Script, or related Workspace
flows. This is a capability workflow, not a canonical executable agent.

Repository implementation routes to GitHub Service Agent with the applicable
Workspace/language standards. ChatGPT Orchestrator classifies cross-system and
external-operation intent. Actual Workspace writes remain separately governed by
`workspace-write-authorization.md` and the exact live-system owner/target.

Legacy names such as `Google Workspace Automation Engineer`, `Workspace
Automation Developer`, or `Workspace Automation Builder` must resolve through the
legacy alias registry and never create a new agent or write authority.

## Core Pre-Build Check

Before building anything, identify:

1. project goal
2. source of truth
3. safe write location
4. owner or approval path
5. smallest working version
6. exact external operations, if any
7. stop condition

Stop when ownership, source of truth, write authority, target, operation, or
approval path is unclear.

## Route Selection

Choose the lightest route that fits:

- **Repository patch/build/debug:** GitHub Service Agent implements the smallest
  safe change, applies relevant Python/Apps Script/Workspace standards, and uses
  directly corresponding tests.
- **Implementation approach evaluation:** ChatGPT Orchestrator applies this
  standard and related runtime constraints to choose a bounded approach; the
  resulting repository work still routes to GitHub Service Agent.
- **External Workspace operation:** remain read-only/dry-run until the exact
  target, action, owner approval, credentials boundary, rollback, and Workspace
  write authorization are established. The capability route is not an agent.

## Builder Outputs

A safe automation design/build should produce the smallest useful set of:

- automation spec
- target inventory
- source-of-truth check
- data-flow map
- read/write operation list
- validation plan
- rollback or disable plan
- repository implementation handoff when code changes are needed
- external-operation authorization handoff when live writes are needed

Do not deploy, create triggers, change sharing, mutate live data, or alter
production files until target, owner, operation, scope, and write authorization
are explicit.

## Required Automation Spec

Before implementation, capture user goal, success condition, systems involved,
exact target IDs when available, trigger type, input source, output destination,
affected fields/tabs/pages/ranges, read operations, write operations, permissions
or OAuth scopes, failure modes, and rollback path.

## Attached Working Set Rule

If attached handoff files apply, inspect `OVERVIEW.md` first, use
`CHANGE_RULES.md` for modification authority, and use `SAFETY_RULES.md` for risk
checks before proposing or implementing changes.

## Build Phases

1. Discovery: inspect only approved sources and identify targets.
2. Spec: define behavior, boundaries, route, and success criteria.
3. Dry-run design: prefer read-only preview, mock clients, or fixture tests.
4. Repository implementation: GitHub Service Agent changes code without live external writes.
5. Validation: QA / Test Agent owns independent evidence where required.
6. External-operation handoff: list exact live-write steps still needing authorization.

## Safety Rules

- Prefer stable IDs over names.
- Separate Drive, Docs, Sheets, Gmail, Calendar, Notion, and Apps Script duties.
- Keep reads, repository implementation, writes, triggers, and deployment actions separate.
- Never write directly to template or master files without exact authorization.
- Never create installable triggers without explicit deployment approval.
- Never broaden sharing or permissions silently.
- Store secrets outside the repository, docs, samples, memory, Notion, and logs.
- Repository implementation authorization never grants Workspace write authority.

## Handoff Checklist

A complete handoff names files changed/generated, targets verified and still
missing, tests run, dry-run evidence, OAuth scopes, live-write approval still
needed, rollback/disable steps, unresolved blockers, and remaining risks.

## Version

0.2.0

## Changelog

- 0.2.0 converts Workspace automation into shared capability routing: repository implementation belongs to GitHub Service Agent and live Workspace operations stay separately authorization-gated (#1324).
- 0.1.1 prior builder standard.
