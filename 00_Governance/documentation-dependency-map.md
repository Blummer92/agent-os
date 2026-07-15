# Agent OS Documentation Dependency Map

## Purpose

This is the **index** for understanding how Agent OS documentation fits together
before implementation work begins. It helps contributors and agents find canonical
documents, avoid duplicate documentation, and choose the correct extension point.

It is an index, not a source of truth. It does not replace any governed standard and
does not restate policy — every concept points back to its canonical document. It does
not move classroom artifacts into GitHub and does not authorize writes to Notion, Drive,
Sheets, or any production system (see `00_Governance/write-authorization-policy.md`).

## Version 1 status: manual now, generated later

This map and its companions are a **manually maintained Version 1**. The long-term goal
is for the inventory, dependency graph, concept ownership, and metadata to be
**generated automatically** from repository structure and file metadata so they stay
synchronized with the repo without manual upkeep. Treat the current files as an
intermediate, reviewable seed for that automation, not a permanent hand-maintained
authority.

## Canonical Start Path

Read in this order unless a narrower task clearly needs less context. This mirrors the
existing "read only what the task needs" rule in `AGENTS.md`; it does not redefine it.

1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. `04_Registry/agent-inheritance-registry.md`
5. `04_Registry/responsibility-matrix.md`
6. the relevant file in `02_Agent_Overlays/`
7. any shared standards referenced by that overlay
8. any relevant tooling README or test documentation

## Companion Documents

Detailed content lives in focused companions under
`00_Governance/documentation-dependency-map/`. Each is an index back to canonical files,
not a new authority:

| Companion | What it answers |
|---|---|
| [`inventory.md`](documentation-dependency-map/inventory.md) | What documents exist, who owns them, status, action, duplicate-risk. |
| [`dependency-graph.md`](documentation-dependency-map/dependency-graph.md) | How documentation and implementation (tooling, tests, connectors, adapters, issues, future Notion/Drive) depend on each other. |
| [`navigation-guide.md`](documentation-dependency-map/navigation-guide.md) | Recommended reading paths per task; the machine-executable form lives in `metadata.yaml`. |
| [`concept-ownership.md`](documentation-dependency-map/concept-ownership.md) | Where every major concept canonically belongs. |
| [`quality-metrics.md`](documentation-dependency-map/quality-metrics.md) | Measurable documentation-quality metrics with formulas and thresholds. |
| [`coverage-validation.md`](documentation-dependency-map/coverage-validation.md) | Coverage questions a future Documentation QA workflow should answer. |
| [`lifecycle-governance.md`](documentation-dependency-map/lifecycle-governance.md) | Lifecycle, ownership transitions, approval, archival, review cadence, automation. |
| [`search-optimization.md`](documentation-dependency-map/search-optimization.md) | Compute-aware changes that reduce agent search cost. |
| [`future-growth.md`](documentation-dependency-map/future-growth.md) | How documentation scales without new duplication. |
| [`issue-97-relationship.md`](documentation-dependency-map/issue-97-relationship.md) | How this map (Issue #98) supports the Navigation Registry plan (Issue #97). |
| [`metadata.yaml`](documentation-dependency-map/metadata.yaml) | Non-authoritative machine-readable layer for agents (documents, concepts, edges, reading paths). |

## Relationship To Issue #97

Issue #98 (this map) and Issue #97 (Navigation Registry improvement plan) are
complementary workstreams: #98 indexes the documentation an implementer must read; #97
plans the cross-system navigation implementation those documents describe. See
[`documentation-dependency-map/issue-97-relationship.md`](documentation-dependency-map/issue-97-relationship.md).

## Validation

A path-existence check for `metadata.yaml` runs inside the existing
`07_Agent_Tests/validate-repo-structure.sh` (no separate QA runner, no new dependency).
Run it with `bash 07_Agent_Tests/validate-repo-structure.sh`.

## Version

0.2.0 — strengthened Issue #98 map: split into index + companions, added machine-readable
metadata, Issue #97 linkage, measurable metrics, and a repo-path validation check.
