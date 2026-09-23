# Documentation Lifecycle Governance

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. This describes how documentation moves through states; it does not replace
> `00_Governance/standards-change-control.md` (the authority for standards changes) or
> `00_Governance/ownership-and-source-of-truth.md`. Where they speak, they win.

## Lifecycle states

```text
Draft -> Review -> Approved -> Implemented -> Maintained
Draft -> Archived
Approved -> Deprecated -> Archived
Implemented -> Deprecated -> Archived
```

- **Draft:** proposed content, not binding.
- **Review:** under owner or QA review.
- **Approved:** governed rule or design accepted.
- **Implemented:** backed by tooling, tests, or active usage.
- **Maintained:** current and actively referenced.
- **Deprecated:** replaced but retained for transition context.
- **Archived:** inactive; retained for history under `06_Archive/`.

## Ownership transitions

Every transition must identify: the primary owner, the supporting owner, the source of
truth, and the rollback/archive path. Ownership is read from
`04_Registry/responsibility-matrix.md` and `04_Registry/ownership-matrix.md`; this file
does not reassign ownership. When a document's owner changes, update the registry first,
then the inventory row here (or regenerate it).

## Approval requirements

- Standards changes follow `00_Governance/standards-change-control.md`.
- Repository writes are executed per `AGENTS.md` (GitHub Service Agent) via a
  `03_Templates/prompts/github-change-request.md` handoff when raised by a non-GitHub agent.
- Governed fields, source-of-truth records, and sharing settings require explicit
  approval per `00_Governance/write-authorization-policy.md`.

## Archival policy

- Move superseded documents to `06_Archive/` rather than deleting them.
- Record the replacement in the archive notes so the transition is traceable.
- Archived documents are read-only reference and are exempt from active-doc metrics.

## Review cadence

- Active standards and overlays: review at each release or when a dependent standard
  changes.
- This map and its companions: review whenever a referenced canonical file is added,
  moved, or retired (a `validate_paths` failure is the signal).
- Archive: no routine cadence; reviewed only on restoration requests.

## Automation opportunities

- Generate the inventory, dependency graph, and concept ownership from repository
  metadata (removes manual drift — the primary Version 1 limitation).
- Extend `validate-repo-structure.sh` with orphan and duplicate-concept checks
  (see `coverage-validation.md`).
- Auto-flag documents whose referenced canonical files changed since last review.
