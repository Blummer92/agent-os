# Navigation Shared Standards

## Purpose

This folder contains the Version 0.9 Navigation Registry documentation stack.
Read these files in order before implementation planning.

## Document Order

1. `navigation-registry-standard.md` — governing standard and boundaries.
2. `navigation-registry-architecture.md` — component flow and workflows.
3. `navigation-registry-data-model.md` — canonical entities, fields, and states.
4. `connector-adapter-framework.md` — connector interface contract.
5. `workspace-discovery-service.md` — discovery and repair recommendations.

## Canonical Authority Map

| Topic | Authoritative file |
|---|---|
| Source of truth | `navigation-registry-standard.md` |
| Write boundary | `navigation-registry-standard.md` |
| Registry ownership | `navigation-registry-standard.md` and `04_Registry/responsibility-matrix.md` |
| Component workflow | `navigation-registry-architecture.md` |
| Cache lifecycle | `navigation-registry-architecture.md` |
| Entities and fields | `navigation-registry-data-model.md` |
| Lifecycle states | `navigation-registry-data-model.md` |
| Validation rules | `navigation-registry-data-model.md` |
| Connector interface | `connector-adapter-framework.md` |
| Connector health and errors | `connector-adapter-framework.md` |
| Discovery workflow | `workspace-discovery-service.md` |
| Drift and repair recommendations | `workspace-discovery-service.md` |

## Conformance Rules

Implementation work must preserve these rules:

- The Navigation Registry is a lookup layer, not a source of truth.
- Cached records never authorize writes or governed-field changes.
- Live systems remain authoritative for their own resources.
- Connector output is evidence, not authority.
- Discovery recommends changes; it does not change live systems by default.
- Integration Manager owns cross-system governance and routing.
- System owners retain live-system approval authority.

## V1 Cleanup Notes

Before declaring Version 1.0, QA should decide whether long files must be split.
If splitting is required, keep this README as the index and move detailed tables
into companion files without changing the canonical authority map.

## Version

0.1.0
