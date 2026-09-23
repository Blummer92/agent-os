# Documentation Coverage Validation

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. These are the questions a future **Documentation QA workflow** should be able to
> answer automatically. Version 1 answers them by manual review plus the one automated
> broken-reference check; the rest are recommended follow-up checks that should **extend**
> `07_Agent_Tests/validate-repo-structure.sh`, not add a parallel runner.

## Questions the repository should be able to answer

1. **Which concepts have no owner?** Every concept in `concept-ownership.md` /
   `metadata.yaml` should name a canonical document and owner. A concept with none is a
   coverage gap.
2. **Which standards are duplicated?** Any concept with more than one document claiming to
   be canonical is a duplicate-risk violation (target: zero).
3. **Which documentation is orphaned?** Any `.md` with no inbound reference and no owner
   in the inventory is an orphan candidate for reference, ownership, or archival.
4. **Which documentation has no tests?** Overlays already require a matching
   `07_Agent_Tests/<overlay>.tests.md` (enforced today). Standards and tooling docs that
   describe validated behavior but have no fixture are coverage gaps.
5. **Which implementation issues reference no canonical documentation?** An issue that
   proposes work without pointing at a canonical standard/overlay/registry file risks
   creating a new source of truth; it should link to the document it extends.

## What is automated in Version 1

- **Broken reference count → 0:** enforced. The repo-structure check verifies every path
  in `metadata.yaml` `validate_paths` exists. See `quality-metrics.md`.
- **Overlay ↔ test coverage:** already enforced by `validate-repo-structure.sh`
  (every overlay has a test file and vice versa).

## Recommended follow-up checks (not built in this pass)

- Orphan-document detection: flag `.md` files never referenced by any other tracked file.
- Duplicate-concept detection: flag concepts mapped to more than one canonical document
  in `metadata.yaml`.
- Issue-to-canonical-doc linkage: flag implementation issues that cite no canonical file.

These should be added as additional checks in the existing script (or a small helper it
calls) so there is one documentation QA entry point, consistent with Agent OS reuse rules.
