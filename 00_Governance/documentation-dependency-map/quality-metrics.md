# Documentation Quality Metrics

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. These metrics measure the documentation system; they do not override any
> governed standard. Format intentionally mirrors the Issue #97 metric structure
> (definition, formula, threshold, owner, cadence) so both workstreams report the same way.

Each metric has a measurable definition so it can later become a regression check inside
`07_Agent_Tests/validate-repo-structure.sh` rather than a subjective review note. The
`broken_reference_count` metric is already partially enforced (see `metadata.yaml`
`validate_paths` + the repo-structure check).

| Metric | Formula / definition | Threshold | Validation owner | Cadence |
|---|---|---|---|---|
| Broken reference count | count of repository paths referenced by the map/metadata that do not exist on disk | 0 | QA / Test Agent | every `validate-repo-structure.sh` run |
| Orphan document rate | docs with no inbound reference and no owner ÷ docs reviewed × 100 | < 10% | QA / Test Agent | per documentation review |
| Duplicate concept rate | concepts with more than one conflicting canonical document ÷ concepts reviewed × 100 | 0 conflicting canonical docs | Integration Manager | per documentation review |
| Documentation coverage | required concepts with ≥1 canonical owner ÷ required concepts × 100 | ≥ 95% for active areas | Integration Manager | per documentation review |
| Documentation retrieval depth | reads needed to reach implementation instructions from `AGENTS.md` via a reading path | ≤ 5 hops for active paths | QA / Test Agent | per reading-path change |
| Average documents before implementation | mean documents an implementer reads before first code change, per reading path | trend down over time | QA / Test Agent | per release |
| Documentation reuse percentage | work items that extend existing docs ÷ work items that touched docs × 100 | trend up over time | Integration Manager | per release |

## Measurement rules

- Count a reference "broken" only when a **repository** path is missing. Notion and Drive
  targets are out of scope for these metrics (this map does not own them).
- Count a concept "duplicated" only when two documents each claim to be canonical for the
  same concept; a reference from one doc to another is not duplication.
- Reading paths are the ones defined in `navigation-guide.md` / `metadata.yaml`.

## Path to regression tests

Version 1 reports these by manual review plus the one automated broken-reference check.
The follow-up Documentation QA work (see `coverage-validation.md`) should turn
orphan-rate, duplicate-concept, and coverage metrics into automated checks that extend
the existing validation script — not a second QA runner.
