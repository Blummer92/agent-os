# Compute-Aware Search Optimization

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. This answers: **what documentation changes would reduce agent compute?** It ties
> directly to the compute-efficiency goals in Issue #97 — fewer, shorter retrievals per
> task means lower cost and faster resolution.

Every recommendation reduces search cost without moving or restating canonical rules.

| Recommendation | Why it reduces compute | Safe boundary |
|---|---|---|
| Root `README.md` links to this map and `AGENTS.md` | Cuts first-hop discovery; agents start at the index instead of scanning folders | Does not move canonical rules |
| Keep folder-level README authority maps (e.g. navigation README) | Local canonical lookup avoids repo-wide search | READMEs reference standards, never restate them |
| Machine-readable `metadata.yaml` reading paths | Agent loads an ordered path by name instead of re-deriving it each task | Non-authoritative; points back to canonical files |
| Stable, unique headings for repeated concepts (Source Of Truth, Write Boundary, Owner, Tests) | Enables precise anchor citation and reduces re-reads | Heading text changes must preserve content |
| Concept ownership matrix consulted before new docs | Prevents duplicate documents that fan out future searches | Matrix is advisory; canonical docs remain authoritative |
| Canonical naming + alias resolution (`legacy-agent-alias-registry.md`) | Fewer failed lookups on renamed/legacy terms | Aliases resolve to canonical agents only |
| One documentation QA entry point (extend `validate-repo-structure.sh`) | Single command to verify references instead of ad-hoc checks | No second QA runner, no new dependency |

## Estimating impact

Version 1 does not measure compute directly. Use the `documentation retrieval depth` and
`average documents before implementation` metrics in `quality-metrics.md` as proxies: a
lower hop-count on the reading paths in `navigation-guide.md` is the observable signal
that these changes are working. The Issue #97 benchmark work should reuse the same
metric format so search-cost improvements are reported consistently across both issues.

## Not in scope

- No live Notion or Drive indexing or search here (those are live surfaces this map does
  not own).
- No new search tooling or dependency; optimization is achieved through indexing,
  cross-links, stable anchors, and the existing validation script.
