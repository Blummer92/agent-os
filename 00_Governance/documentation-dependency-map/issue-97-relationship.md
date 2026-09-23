# Relationship To Issue #97

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. Explains how Issue #98 (this documentation map) and Issue #97 (Navigation
> Registry improvement plan) support each other as complementary workstreams.

## The split

- **Issue #97** plans the *implementation*: cross-system navigation across Notion, Google
  Drive, and GitHub — reuse analysis, external-pattern review, cross-system model, naming
  and relationship rules, adapter specs, a testing plan, and measurable success criteria.
- **Issue #98** (this map) indexes the *documentation* an implementer of #97 must read,
  and defines where new documentation belongs so #97 does not create duplicate authorities.

Neither owns the other: #98 points at canonical docs; #97 changes and extends them through
the normal governance and GitHub Change Request flow.

## Where #98 directly supports #97

| Issue #97 area | What #98 provides |
|---|---|
| Navigation Registry | Reading path + inventory rows for the full navigation stack (`navigation-guide.md`, `inventory.md`). |
| Workspace Discovery | Canonical owner and duplicate-risk for discovery/drift (`concept-ownership.md`). |
| Connector / adapter specs | Points every future Notion/Drive/GitHub adapter back to `connector-adapter-framework.md` instead of a new framework. |
| Testing | Coverage questions and the reuse-the-existing-runner rule (`coverage-validation.md`, `quality-metrics.md`). |
| Documentation ownership | Concept ownership matrix so #97 extends the right file. |
| Agent workflow validation | Machine-executable reading paths in `metadata.yaml` for future automated routing. |
| Compute efficiency | Compute-aware search optimization in `search-optimization.md`, using #97's metric format. |

## Shared conventions

Both issues report metrics with the same fields (definition, formula, threshold, owner,
cadence) and both respect the same source-of-truth and read-only boundaries. Success
metrics for navigation quality remain owned by Issue #97; this map does not restate or
supersede them.

## Recommended cross-link

Issue #97 and Issue #98 should reference each other in their descriptions so reviewers can
navigate between the plan and the documentation index. This is a GitHub issue-text change,
not a repository change, and is left to the issue owner.
