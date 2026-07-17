# Issue Structure And Dependency Contract

## Purpose

Define one machine-readable contract for Agent OS standalone issues, parent roadmaps, child implementations, investigations, decision gates, validation work, documentation, migrations, and cleanup.

This standard extends `issue-acceptance-automation.md`. It does not replace readiness or pull-request acceptance logic and does not authorize implementation, external writes, readiness changes, issue closure, review approval, or merge.

## Stable issue roles

Use exactly one role:

- `standalone`
- `parent-roadmap`
- `child-implementation`
- `investigation`
- `decision-gate`
- `validation`
- `documentation`
- `migration`
- `cleanup`

## Stable execution modes

Use exactly one mode:

- `parallel-safe`
- `sequential`
- `decision-gated`
- `manual-review`
- `blocked`

## Dependency types

Every dependency must be classified as one of:

- `hard`: completion is required before work may begin or close.
- `soft`: useful context or sequencing guidance, but not a blocker.
- `decision`: a human decision is required before the dependent work may proceed.
- `documentation`: an existing documentation source must be extended or consumed.
- `follow-up`: intentionally deferred work that does not block the current issue.

Do not use an untyped `Depends on` list for automation-ready work.

## Canonical stable fields

Templates and automation should use these field identifiers or matching visible headings:

```text
issue-role
issue-tier
parent-issue
issue-code
primary-owner
supporting-owners
execution-mode
readiness
source-of-truth
external-write
objective
value
scope
non-goals
allowed-surfaces
forbidden-surfaces
inputs
outputs
dependencies
blockers
validation
documentation
acceptance
definition-of-done
stop-conditions
handoff-target
remaining-risks
rollback
idempotency
manual-review
closure-evidence
```

## Required common contract

Every implementation-capable Tier 1 or Tier 2 issue must state:

- issue role and tier;
- parent issue or `none`;
- issue code;
- primary and supporting owners;
- execution mode and readiness candidate;
- source of truth and external-write boundary;
- objective and value;
- scope and non-goals;
- allowed and forbidden files, systems, or governed surfaces;
- inputs consumed and outputs produced;
- typed dependencies and blockers;
- required tests and documentation, including `not applicable` when appropriate;
- acceptance criteria and definition of done;
- stop conditions;
- next handoff;
- remaining risks;
- closure evidence.

Tier 0 may use the reduced contract from `issue-acceptance-automation.md`, but must still declare role, code, owner, allowed surface, validation, and completion evidence.

## Tier 2 controls

Tier 2 governed or cross-system work must additionally state:

- authorization source;
- external systems;
- exact write operations;
- least-privilege requirements;
- human approval points;
- rollback;
- migration or compatibility behavior;
- idempotency;
- failure handling;
- manual-review behavior;
- data, credential, and secret handling;
- required audit evidence.

A write-capable Tier 2 issue is not `ready` when rollback, authorization, idempotency, or manual-review behavior is missing.

## Parent-roadmap contract

A parent roadmap coordinates work; it must not duplicate every child body.

Required parent content:

- roadmap objective and measurable final outcome;
- primary and supporting owners;
- child issue table;
- typed dependency graph;
- recommended sequence;
- parallel-safe and sequential classifications;
- decision gates;
- integration checkpoints;
- rollout stages;
- parent-level risks;
- parent-level definition of done;
- roll-up checklist;
- evidence required from each child;
- final reconciliation step.

Use this table shape:

| Code | Child issue | Owner | Depends on | Mode | Expected output | Status |
|---|---|---|---|---|---|---|

A parent must not close while a hard child remains open, blocked, or missing required closure evidence.

## Child-implementation contract

A child issue must include:

- parent issue link;
- unique child code;
- exact objective;
- bounded scope and explicit non-goals;
- primary and supporting owners;
- typed dependencies;
- predecessor output consumed;
- output produced for the next child;
- allowed and forbidden surfaces;
- tests and documentation;
- acceptance criteria and definition of done;
- stop conditions;
- parent-update requirement.

A child must be independently executable once its hard and decision dependencies are satisfied. It must not rely on unwritten parent assumptions.

## Checklist children versus separate issues

Use checklist children when all of the following are true:

- one owner and one pull request can complete the work;
- the tasks share one release boundary;
- no task needs independent readiness, labels, or approval;
- failures can be reviewed in the parent issue.

Create separate child issues when any of the following is true:

- different primary owners;
- independent pull requests or releases;
- a decision gate blocks later implementation;
- separate external-write authorization is required;
- work can proceed in parallel;
- closure evidence must be tracked independently.

## Readiness and dependency rules

- `status:ready` is evidence only; it does not authorize implementation or writes.
- A child with an unresolved hard dependency is `blocked`.
- A child with an unresolved decision dependency is `needs-decision`.
- Ambiguous ownership, authorization, source of truth, or routing is `needs-decision`.
- Historical issues missing the new fields should warn by default.
- Missing safety-critical Tier 2 controls should fail even for legacy issues before implementation begins.

## Report-only validation contract

The first validation rollout must remain offline and report-only.

It may detect:

- missing parent link for a child;
- missing child table for a parent;
- missing or duplicate issue codes;
- invalid role, owner, execution mode, or dependency type;
- missing readiness evidence;
- unresolved hard or decision dependencies;
- dependency cycles when the full issue set is available;
- missing allowed or forbidden surfaces;
- missing tests, docs declaration, acceptance, or definition of done;
- missing Tier 2 stop conditions, rollback, idempotency, authorization, or manual-review behavior;
- parent closure attempted while children remain incomplete.

It must not close issues, mutate readiness, apply or remove labels, approve work, or merge pull requests.

## Machine-checkable metadata

Issues may include this optional block:

```yaml
agent_os_issue_structure:
  schema_version: 1
  role: child-implementation
  tier: 2
  issue_code: GB7
  parent_issue: 210
  primary_owner: github-service-agent
  supporting_owners:
    - qa-test-agent
    - integration-manager
  execution_mode: decision-gated
  readiness: needs-decision
  source_of_truth: GitHub
  external_write: github-pr-comment
  dependencies:
    - issue: 215
      type: documentation
    - issue: 216
      type: decision
  allowed_surfaces: []
  forbidden_surfaces: []
  required_tests: []
  required_docs: []
  stop_conditions: []
  rollback: []
  idempotency: []
  manual_review: []
  closure_evidence: []
```

Metadata narrows checks but never replaces the visible issue body, governance, or reviewer judgment.

## Migration and compatibility

- New issues should use this contract after the templates land.
- Open issues should be upgraded before implementation when missing fields would force an agent to guess.
- Legacy issues remain valid historical records.
- Legacy omissions should normally produce warnings.
- Safety-critical omissions for write-capable Tier 2 work produce blocking findings.
- Existing `agent_os_issue_acceptance` metadata remains supported.
- The structure validator is an extension of the existing acceptance package, not a competing system.
