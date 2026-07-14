# Workspace Discovery Service

## Purpose

Define a platform-independent service that discovers, validates, and recommends
Navigation Registry updates without modifying live systems or granting write
authorization.

## Responsibilities

Discovery finds resources and metadata. Validation compares discovered metadata
against registry entries. Recommendation proposes safe changes. Repair updates
registry or live systems only after owner approval. Operational writes remain
outside this service unless explicitly authorized through the owning system.

The service detects new, renamed, moved, deleted, duplicate, permission-changed,
or stale resources; orphaned relationships; and source-of-truth conflicts.

## Discovery Lifecycle

```text
Discovery Requested
  -> Connector Scan
  -> Normalization
  -> Registry Comparison
  -> Drift Classification
  -> Recommendation Generation
  -> Human Review Decision
  -> Registry Refresh Recommendation
  -> Completed
```

Transitions require a run id, connector name, evidence bundle, and current
state. Stop when authorization, ownership, target scope, connector access, or
source of truth is unclear. Restart only from the last safe checkpoint after the
blocking condition is resolved.

## Discovery Workflow

```text
Scheduled/manual/event trigger
  -> connector discovery
  -> normalize metadata to the data model
  -> compare against Navigation Registry
  -> classify drift and severity
  -> recommend updates
  -> queue human review when required
  -> approved registry refresh or handoff
```

Stop when a connector is unavailable, ownership is unclear, permissions changed,
source of truth conflicts, duplicate candidates exist, or a recommendation would
change governed records without approval.

## Discovery Modes

| Mode | Use |
|---|---|
| Full scan | Initial setup, major migration, audit, or suspected drift. |
| Incremental scan | Routine refresh using modified timestamps or deltas. |
| Targeted scan | Known resource, workflow, folder, database, or repo. |
| Manual discovery | Human-requested investigation or recovery. |
| Scheduled discovery | Nightly/weekly background validation. |
| Event-driven discovery | Future webhook or trigger-based refresh. |

## Decision Trees

Rename: if stable id matches and only display_name changed, recommend display
name refresh; if aliases collide, require human review; if id changed too, treat
as possible duplicate or replacement.

Move: if stable id matches and parent/path changed, recommend parent/path
refresh; if sharing boundary changed, escalate as permission drift; if source of
truth changed, stop for governance review.

Delete: if registry entry is missing from live system, retry verification; if
confirmed deleted, recommend inactive or archive; if permission may hide it,
escalate to owner instead of archiving.

Duplicate: if one alias/name/scope maps to multiple targets, block automatic
resolution; compare owners, parents, versions, and relationships; recommend merge
or human review.

Permission change: if access boundary differs, mark critical; stop all write
paths; route to system owner with evidence.

Ownership change: if live owner differs from registry owner, verify both sources;
if conflict remains, stop and request owner review.

Orphan relationship: if source or target is missing, verify live system; if
confirmed missing, recommend relink, deactivate, or archive relationship.

Stale cache: if freshness window expired, recommend refresh; if write-impacting
action is requested, require live verification first.

## Drift Classification Framework

| Severity | Meaning | Automatic action |
|---|---|---|
| Informational | No behavior change; metadata note only. | record warning |
| Low | Stable id intact; safe metadata changed. | recommend refresh |
| Medium | Relationship, parent, or freshness issue. | verify before action |
| High | deletion, duplicate, owner, or broken relation. | human review |
| Critical | permission, source-of-truth, or security boundary issue. | stop and escalate |

| Drift | Detection | Confidence | Verification | Escalation | Approval |
|---|---|---|---|---|---|
| Rename | same id, changed name | high | connector read | none unless alias conflict | low-risk refresh |
| Move | same id, changed parent/path | high | connector read | owner if boundary changed | owner if governed |
| Delete | id not found | medium | retry and permission check | system owner | required |
| Duplicate | alias/name collision | medium | compare evidence | registry owner | required |
| Broken relationship | missing source/target | high | live lookup | Integration Manager | required |
| Ownership change | owner mismatch | medium | live owner check | system owner | required |
| Permission change | access mismatch | high | permission read | system owner | required |
| Stale cache | freshness exceeded | high | refresh check | none unless blocked | not for read-only |

## Repair Recommendation Framework

| Recommendation | Trigger | Evidence | Approval | Registry impact | Live impact | Rollback |
|---|---|---|---|---|---|---|
| Refresh cache | stale or low drift | timestamps, connector read | cache owner | update cache metadata | none | restore prior cache row |
| Update alias | rename or user term | stable id, alias evidence | registry owner | alias change | none | restore previous alias |
| Merge duplicate | duplicate resources | comparison bundle | human owner | consolidate entries | none by default | restore tombstoned entry |
| Relink relationship | orphan/broken edge | source/target evidence | Integration Manager | relationship update | none | restore prior edge |
| Archive entry | confirmed deletion | retry proof | system owner | state to Archived | none | reactivate if found |
| Deactivate entry | inaccessible/deprecated | owner evidence | system owner | inactive flag | none | reactivate after verification |
| Human review | conflict/low confidence | drift summary | required | none until approved | none | not applicable |
| GitHub Change Request | governed repo change | proposed docs delta | GitHub owner | repo docs change | GitHub only | PR revert |

Every recommendation includes run id, affected entries, confidence score,
approval requirement, owner, source evidence, rollback note, and whether it is
registry-only or live-system-impacting.

## Connector Discovery Contract

Each connector must define connector name, supported resource types, stable
identifier strategy, metadata returned, verification strategy, relationship
discovery, cache freshness strategy, rate limiting behavior, permission model,
failure reporting, and adapter version.

Required metadata: stable identifier, resource type, display name, parent,
owner, permission metadata, modified timestamp, verification method,
source-of-truth claim, freshness window, and relationship hints. Connector output
must normalize into the Navigation Registry Data Model.

Adapters may add extension metadata. They must not redefine core fields, bypass
live verification, or convert discovery output into write authorization.

## Discovery Validation Matrix

| Condition | Expected behavior | Approval | Registry action | Operational action | Human review |
|---|---|---|---|---|---|
| Missing owner | stop | owner required | flag invalid | none | yes |
| Duplicate alias | block resolution | registry owner | mark duplicate | none | yes |
| Broken relationship | verify source/target | Integration Manager | recommend relink | none | yes |
| Permission revoked | stop and escalate | system owner | mark critical | none | yes |
| Deleted resource | retry then confirm | system owner | archive/deactivate recommendation | none | yes |
| Circular reference | classify cycle | registry owner | flag dependency | none | yes |
| Cache expired | refresh recommendation | cache owner | refresh metadata | none | no if read-only |
| Connector offline | partial run | none | record failure | retry | no unless urgent |
| Source conflict | stop | governance owner | flag conflict | none | yes |

## Scheduling Model

| Schedule | Purpose | Scope | Expected runtime | Priority | Rate limit rule |
|---|---|---|---|---|---|
| Startup scan | active workflow readiness | active resources only | short | high | strict batching |
| Nightly scan | routine freshness | common systems | medium | normal | incremental first |
| Weekly validation | deeper consistency | high-value registries | long | normal | off-peak batches |
| Monthly audit | governance drift | all approved systems | long | low | slow full scan |
| Manual discovery | targeted issue | named target | variable | high | minimal scope |
| Emergency discovery | permission/source conflict | affected system | short | critical | pause noncritical work |
| Event-driven | future webhook refresh | changed resource | short | high | debounce events |

## Performance Objectives

Routine cache lookup should complete before live search. Target at least 80%
cache hit rate for common workflow resources after pilot stabilization. Batch
connector reads whenever supported. Keep targeted discovery narrow enough to
avoid full workspace scans. Prefer incremental deltas for nightly scans. Maximum
stale windows are system-specific and must be declared by each connector.

## Failure Recovery Model

Connector timeout: retry with backoff, then mark partial. API outage: stop that
system and report. Authentication failure: stop and route to owner. Permission
loss: mark critical and block write-impacting actions. Interrupted discovery:
resume from checkpoint or restart safely. Partial discovery: keep successful
read-only findings but mark run partial. Corrupted cache: stop refresh and use
last known good snapshot. Duplicate identifiers: block automatic repair.
Registry corruption: create GitHub Change Request. Conflicting metadata: require
human review.

## Workspace Discovery State Machine

States: Pending, Scanning, Normalizing, Comparing, Drift Detected,
Recommendation Generated, Awaiting Review, Approved, Registry Updated,
Completed, Cancelled, Failed, Deferred, Expired, Retry Scheduled.

Valid primary path:

```text
Pending -> Scanning -> Normalizing -> Comparing -> Drift Detected
  -> Recommendation Generated -> Awaiting Review -> Approved
  -> Registry Updated -> Completed
```

No-drift path: Comparing -> Completed. Failure path: any active state -> Failed
or Retry Scheduled. Governance-blocked path: any active state -> Deferred.
Expired runs cannot update registry metadata without a new run.

## Failure Handling

Offline connector: mark discovery partial and retry later. API unavailable: stop
for that system and report. Revoked permission: escalate to owner. Missing
resource: verify before marking inactive. Duplicate identifier: block automatic
repair. Partial success: apply only approved low-risk recommendations.
Interrupted run: resume from checkpoint if supported, otherwise restart safely.

## Security Review

Trust boundaries: connectors provide evidence, not authority. Cache records aid
navigation, not decisions. Registry rules live in GitHub governance. Approval
boundaries remain with system owners. Audit records must include run id,
timestamp, connector, evidence, recommendation, reviewer requirement, and final
disposition. Evidence retention must avoid storing secrets, private message
content, credentials, or unnecessary student data.

## Security And Governance

GitHub remains the Agent OS source of truth. Cached metadata is non-authoritative.
Discovery never grants write permission. System owners retain authority over live
records. All recommendations must be auditable and include source evidence,
run id, timestamp, connector, and reviewer requirement.

## Expansion Model

New connectors for Notion, Drive, GitHub, Gmail, Calendar, Canvas, Adobe, Figma,
or future systems plug in through the connector contract. They may add adapter
metadata but must not change core registry fields or bypass live verification.

## Future Evolution

1. Discovery V1: design-only recommendations and manual review.
2. Connector Framework: formal adapter specs; governance approval required.
3. Read-only Discovery Runner: implementation proposal; approval required.
4. Registry Refresh Engine: controlled cache updates; approval required.
5. Event-driven Discovery: webhook/trigger model; security review required.
6. Autonomous Recommendation Engine: recommendations only; governance review.
7. AI-assisted Discovery: explainable evidence and human approval required.

## Validation Against Current Standards

Compatible with the Navigation Registry Standard because discovery is a lookup
and recommendation service only. Compatible with the Architecture because it uses
the shared workflow, drift, and expansion model. Compatible with the Data Model
because connector output normalizes to core entities and fields. Compatible with
the Integration Manager overlay and Responsibility Matrix because the Integration
Manager owns cross-system routing while system owners retain live authority.

This design does not implement code, create databases, write operational cache
records, modify Notion, modify Drive, modify Apps Script, or change production
systems.

## Roadmap

1. QA review of this design.
2. Define connector adapter specs.
3. Choose operational cache destination.
4. Design read-only discovery runner.
5. Add fixtures for drift, duplicates, and permissions.
6. Pilot Notion, Drive, and GitHub discovery before broader expansion.

## Version

0.1.1
