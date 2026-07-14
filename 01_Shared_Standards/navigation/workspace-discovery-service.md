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
| Full scan | Initial setup, major migration, or audit. |
| Incremental scan | Routine refresh using modified timestamps or deltas. |
| Targeted scan | Known resource, workflow, folder, database, or repo. |
| Manual discovery | Human-requested investigation or recovery. |
| Scheduled discovery | Nightly/weekly background validation. |
| Event-driven discovery | Future webhook or trigger-based refresh. |

## Drift Model

| Drift | Detection | Severity |
|---|---|---|
| Rename | same stable id, changed display_name | low |
| Move | same stable id, changed parent/path | medium |
| Delete | registry id missing from live system | high |
| Duplicate | same alias/name/scope maps to many targets | high |
| Broken relationship | source or target missing/invalid | high |
| Ownership change | owner differs from registry | high |
| Permission change | access boundary differs | critical |
| Stale cache | freshness window exceeded | medium |

Critical and high drift require human review before registry refresh.

## Repair Recommendations

Recommendations may include refresh cache, update display name, update aliases,
relink relationship, archive deleted entry, merge duplicates, mark inactive,
request owner review, or create a GitHub Change Request. Recommendations must
include evidence, affected entries, severity, proposed owner, and approval need.

## Connector Discovery Contract

Each connector must provide stable identifier, resource type, display name,
parent, owner, permission metadata, modified timestamp, verification method,
source-of-truth claim, freshness window, and supported relationship hints.
Connector output must normalize into the Navigation Registry Data Model.

## Scheduling Strategy

Run startup discovery only for active workflows. Use nightly incremental scans
for common systems, weekly full validation for high-value registries, manual
refresh for teacher or governance requests, and emergency refresh after known
permission or source-of-truth changes. Respect platform rate limits and prefer
batching over repeated search.

## Performance Strategy

Prefer incremental refresh, batched connector calls, lazy validation for cold
resources, cache warming for active workflows, parallel discovery by system when
rate limits allow, and live API minimization. Target most routine navigation
lookups to resolve from cache, while any write-impacting action still verifies
live state.

## Failure Handling

Offline connector: mark discovery partial and retry later. API unavailable: stop
for that system and report. Revoked permission: escalate to owner. Missing
resource: verify before marking inactive. Duplicate identifier: block automatic
repair. Partial success: apply only approved low-risk recommendations.
Interrupted run: resume from checkpoint if supported, otherwise restart safely.

## Security And Governance

GitHub remains the Agent OS source of truth. Cached metadata is non-authoritative.
Discovery never grants write permission. System owners retain authority over live
records. All recommendations must be auditable and include source evidence,
run id, timestamp, connector, and reviewer requirement.

## Expansion Model

New connectors for Notion, Drive, GitHub, Gmail, Calendar, Canvas, Adobe, Figma,
or future systems plug in through the connector contract. They may add adapter
metadata but must not change core registry fields or bypass live verification.

## Roadmap

1. QA review of this design.
2. Define connector adapter specs.
3. Choose operational cache destination.
4. Design read-only discovery runner.
5. Add fixtures for drift, duplicates, and permissions.
6. Pilot Notion, Drive, and GitHub discovery before broader expansion.

## Version

0.1.0
