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

## Pre-Create Preflight

Before an agent proposes or creates a new Notion-facing field, dashboard,
database, workflow, or prompt, it consults the cached Notion navigation index
through the advisory preflight in `08_Tooling/notion-navigation-client/` (see its
README for the interface). The preflight checks, in order, for an exact or
deterministically normalized existing match, then for Duplicate / Drift Watchlist
evidence, then returns the owner and source-of-truth route to verify live next.
Its finite outcomes are `existing-match`, `duplicate-risk-review`,
`no-cached-match`, `stale-or-unverified`, and `manual-review`.

The preflight is cached evidence, not authority. `no-cached-match` is not proof that
creating is safe, a duplicate-risk finding routes to human review and never triggers
automatic merge, rename, retirement, or cleanup, and every outcome requires live
verification of the owning system before any write or governed-field decision. It
adds no registry, cache, or deduplication system, and it does not replace the GitHub
bug-issue duplicate admission owned elsewhere.

## Pre-Create Reconciliation

Before proposing new Agent OS work, a caller classifies it with
`navigation_registry.reconciliation.classify_proposed_work` (#3308). This is a pure,
deterministic function. Callers acquire all evidence and pass it in:

- the preflight outcome above, when the work touches Notion-facing structures;
- a complete, bounded GitHub issue search, with each open issue's lifecycle stage
  taken from the PR-lineage acquisition where one exists;
- matching reusable-capability registry rows.

It returns exactly one disposition: `reuse-current-owner`, `continue-current-work`,
`extend-existing-capability`, `historical-regression-evidence`,
`superseded-or-retired`, `candidate-new-work`, or `manual-review`.

The rules apply in this order:

1. GitHub lineage is authoritative and decides first. A current open owner of the same
   objective wins, or the current successor of closed same-objective history.
   Contradictory successor facts, a closed successor, or more than one open owner or
   successor become `manual-review`.
2. Open work that is only related, or related history with a successor, becomes
   `manual-review`.
3. A registered capability is extended rather than reimplemented, even where closed
   history of the same objective exists.
4. Closed issues are evidence only and are never returned as actionable owners.
5. Navigation evidence is advisory and only gates new work. Anything other than a fresh
   `no-cached-match` becomes `manual-review`, and so does an incomplete search; neither
   is ever treated as a no-match.

`candidate-new-work` grants no creation authority. Issue creation still passes its
existing admission (bugs: the duplicate and root-cause admission). Continuation,
Codespaces and GCE routing, CKR6 consumption and backlog selection stay with their
existing owners.

## Roadmap

1. Approve architecture and tests.
2. Define operational cache destination and refresh owner.
3. Design read-only discovery tooling.
4. Add system-specific adapter specs.
5. Add QA fixtures for drift and duplicate detection.
6. Pilot with Notion, Drive, and GitHub before adding more systems.

## Version

0.1.0
