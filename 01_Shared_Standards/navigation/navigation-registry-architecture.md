# Navigation Registry Architecture

## Purpose

Define the implementation-independent data model and workflows for the
Navigation Registry. Operational tools must follow this architecture without
changing source-of-truth ownership or write authorization rules.

## Registry Schemas

| Registry | Purpose | Required fields | Owner | Source of truth |
|---|---|---|---|---|
| System | Lists connected systems and capabilities. | system, status, owner, auth model, verification method | Integration Manager | GitHub governance plus live system state |
| Database | Locates structured stores such as Notion databases or Sheets. | system, database id/path, name, owner, last verified | System owner | Live system |
| Page | Locates pages or documents. | system, page id/path, title, parent, owner, last verified | System owner | Live system |
| File | Locates files and artifacts. | system, file id/path, name, mime/type, owner, last verified | System owner | Live system |
| Folder | Locates approved containers. | system, folder id/path, name, owner, sharing boundary | System owner | Live system |
| Workflow | Maps repeatable lookup flows. | workflow name, trigger, steps, owner, stop conditions | Integration Manager | GitHub |
| Relationship | Links resources across systems. | source, target, relationship type, cardinality, confidence | Integration Manager | Live systems verified through cache |
| Alias | Resolves user terms to canonical resources. | alias, canonical target, scope, owner, human review flag | Integration Manager | GitHub for rules; live systems for resources |
| Template | Locates governed templates. | template id/path, system, purpose, owner, version | Template owner | GitHub or live system by template type |

Optional fields may include tags, course, unit, audience, freshness window,
duplicate risk, related standards, and deprecation notes.

## Validation Rules

Every entry must declare an owner, source of truth, write boundary, last
verification state, and human-review flag. Entries with missing identifiers,
duplicate aliases, stale verification, or source-of-truth conflicts are lookup
warnings, not actionable authority.

## Relationship Model

Relationships are typed edges between registry entries. Supported cardinalities
are one-to-one, one-to-many, and many-to-many. Each edge stores relationship
type, direction, confidence, source evidence, and last verified state.

Example path: Lesson -> Slides -> Worksheet -> Assessment -> Resources ->
Images -> Standards. Agents may traverse this graph for discovery, but must
verify the live target before writes or governed decisions.

## Navigation Workflow

```text
User request
  -> classify intent and likely owner
  -> query Navigation Registry
  -> resolve aliases and relationships
  -> check human-review and drift flags
  -> verify live system state when action affects a live artifact
  -> confirm authorization and owner
  -> perform authorized action or produce handoff
```

Stop when the target, owner, source of truth, authorization, or live verification
result is unclear. Stop before any sharing, readiness, status, ownership,
approval, governed-field, or irreversible change without explicit approval.

## Cache Lifecycle

Creation starts from approved discovery or manually approved registry entries.
Refresh may be scheduled, manual, or event-triggered by approved tooling.
Invalidation occurs when permissions, identifiers, ownership, paths, titles, or
relationships change. Expiration is set per system based on volatility.

Cached identifiers, titles, aliases, relationships, timestamps, and warnings may
be stored. Cached data must never be treated as authoritative for live content,
approvals, grades, readiness, ownership, permissions, sharing, or source of
truth.

## Drift And Recovery

Drift exists when cache and live state disagree. Agents surface the conflict,
identify likely authority, avoid writes, and recommend refresh, owner review,
or registry correction. Deleted or permission-blocked resources become inactive
until verified by the system owner.

## Cross-System Expansion

Each new system must define resource types, stable identifiers, verification
method, owner, read boundary, write boundary, freshness window, and drift rules.
Notion, Drive, GitHub, Gmail, Calendar, Canvas, Adobe, and Figma all connect
through the same registry fields; system-specific adapters translate their live
APIs into the common model.

## Workspace Discovery Service

A future discovery service may find new resources, detect renames, deletions,
moves, permission changes, duplicate resources, and relationship drift. It may
recommend repairs or refresh cache metadata. It must not change live systems or
governed records without owner approval.

## Performance Targets

Aim for registry lookup before live API calls, high cache-hit rates for common
resources, batched verification, lazy loading for rarely used relationships, and
prefetch for active workflows. The target is fewer live searches while keeping
writes gated by live verification.

## Failure Modes

Stale cache: warn, verify live state, refresh or hand off. Missing ID: search
only if authorized, then flag for review. Permission change: stop and route to
owner. Deleted resource: mark inactive after verification. Offline system: defer
live action and produce handoff. Duplicate resource: require human review before
write or relationship repair.

## Roadmap

1. Approve architecture and tests.
2. Define operational cache destination and refresh owner.
3. Design read-only discovery tooling.
4. Add system-specific adapter specs.
5. Add QA fixtures for drift and duplicate detection.
6. Pilot with Notion, Drive, and GitHub before adding more systems.

## Version

0.1.0
