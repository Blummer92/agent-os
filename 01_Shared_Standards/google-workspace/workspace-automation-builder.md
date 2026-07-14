# Workspace Automation Builder

## Purpose
Use this standard when designing or building Google Workspace automations for
Drive, Docs, Sheets, Gmail, Calendar, Apps Script, or related workspace flows.
This is a builder workflow, not a new agent. Route legacy names such as
Workspace Automation Developer to the Google Workspace Automation Engineer unless
the registry says otherwise.

## Core Pre-Build Check
Before building anything, identify:

1. project goal
2. source of truth
3. safe write location
4. owner or approval path
5. smallest working version
6. stop condition

Stop when ownership, source of truth, write authority, target, or approval path
is unclear.

## Route Selection
Choose the lightest route that fits:

- Patch existing code: inspect touched files, related tests, known bugs, and the
  smallest relevant references first; prefer the smallest safe patch and reuse
  existing modules.
- Build a new project: use existing Python standards or scaffolding patterns;
  create the smallest runnable version, keep orchestration thin, and put business
  logic into reusable modules.
- Debug or optimize: identify the failing surface, inspect the smallest relevant
  path, add or update a regression test, and produce bug-learning handoff notes.
- Evaluate implementation approach: keep comparison brief, recommend the fastest
  maintainable path, and prefer Python unless Apps Script is clearly better for
  Workspace runtime constraints.

## Builder Outputs
A safe automation build should produce the smallest useful set of:

- automation spec
- target inventory
- source-of-truth check
- data-flow map
- read/write operation list
- validation plan
- rollback or disable plan
- deployment handoff

Do not deploy, create triggers, change sharing, mutate live data, or alter
production files until target, owner, scope, and write authorization are explicit.

## Required Automation Spec
Before implementation, capture user goal, success condition, systems involved,
exact target IDs when available, trigger type, input source, output destination,
affected fields/tabs/pages/ranges, read operations, write operations, permissions
or OAuth scopes, failure modes, and rollback path.

If any target or write scope is unclear, stop before building live-write code.

## Attached Working Set Rule
If attached handoff files apply, inspect `OVERVIEW.md` first, use
`CHANGE_RULES.md` for modification authority, and use `SAFETY_RULES.md` for risk
checks before proposing or implementing changes.

## Build Phases
1. Discovery: inspect only approved sources and identify targets.
2. Spec: define behavior, boundaries, route, and success criteria.
3. Dry-run design: prefer read-only preview, mock clients, or fixture tests.
4. Implementation: build local code or Apps Script plan without live writes.
5. Validation: test pure logic, mocked API calls, and expected receipts.
6. Approval handoff: list live-write steps still needing explicit approval.

## Safety Rules
- Prefer stable IDs over names.
- Separate Drive, Docs, Sheets, Gmail, Calendar, Notion, and Apps Script duties.
- Keep reads, writes, triggers, and deployment actions separate.
- Never write directly to template or master files.
- Never create installable triggers without explicit deployment approval.
- Never broaden sharing or permissions silently.
- Store secrets outside the repository, docs, samples, memory, Notion, and logs.

## Handoff Checklist
A complete handoff names files changed or generated, targets verified and still
missing, tests run, dry-run evidence, OAuth scopes, live-write approval still
needed, rollback or disable steps, unresolved blockers, and remaining risks.

## Version
0.1.1
