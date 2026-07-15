# Documentation Dependency Graph

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth; canonical rules live in the referenced files. **Manual Version 1 — should
> eventually be generated** from cross-references in the repository. The structured
> edges also live in `metadata.yaml` under `dependency_edges`.

This graph shows both **documentation dependencies** (what you read before what) and
**implementation dependencies** (docs → tooling → tests → connectors/adapters → issues,
plus planned Notion/Drive relationships). Notion and Drive are live working surfaces;
edges to them are marked `planned`/`future` and this map does not own or authorize them.

## Governance-to-work flow

```text
AGENTS.md
  -> 00_Governance/ownership-and-source-of-truth.md
  -> 00_Governance/write-authorization-policy.md
  -> 04_Registry/agent-inheritance-registry.md
  -> 04_Registry/responsibility-matrix.md
  -> 02_Agent_Overlays/<selected-owner>.md
     -> 01_Shared_Standards/<referenced-standard>.md
        -> 08_Tooling/<tool>/README.md            (when implementation exists)
        -> 07_Agent_Tests/ and tests/ fixtures    (when validation exists)
        -> 03_Templates/prompts/github-change-request.md -> GitHub issue/PR
```

## Navigation implementation flow (documentation + implementation)

```text
02_Agent_Overlays/integration-manager.md
  -> 01_Shared_Standards/navigation/README.md
     -> navigation-registry-standard.md
     -> navigation-registry-architecture.md
     -> navigation-registry-data-model.md
     -> connector-adapter-framework.md          (connector contract)
        -> 08_Tooling/notion-navigation-client/  (Notion adapter implementation)
           -> tests/ and 07_Agent_Tests/         (fixtures, validation)
     -> workspace-discovery-service.md           (discovery, drift)
  -> 01_Shared_Standards/notion/notion-navigation-index-standard.md
  -> implementation issues #97 (plan) and #98 (this map)
  ~> [planned] Notion source sections            (live working surface; read-only)
  ~> [future]  Google Drive artifact destinations (live working surface; read-only)
  ~> [future]  Google Drive / GitHub adapter specs (inherit connector-adapter-framework)
```

`->` documentation/implementation dependency that exists today.
`~>` planned/future relationship; not owned here and not authorized by this map.

## Edge types

- `reads_before` — recommended reading order between docs.
- `governed_by` — a doc/tool is bound by a governance or standard file.
- `implemented_by` — a standard is realized by tooling under `08_Tooling/`.
- `validated_by` — a doc/tool is checked by tests or `validate-repo-structure.sh`.
- `planned` / `future` — a relationship to Notion, Drive, or an unbuilt adapter/spec.

## Circular, orphaned, and duplicated concepts

- **Circular:** none required today. If architecture and data-model docs begin
  cross-citing bidirectionally, keep the data model authoritative for entities/fields
  and the architecture doc authoritative for workflows to avoid a cycle.
- **Orphaned:** candidate orphans are docs with no inbound reference and no clear owner;
  `coverage-validation.md` lists the question and `metadata.yaml` seeds detection.
- **Duplicated concepts:** source-of-truth text, connector behavior, and Notion cache
  behavior must not be restated per overlay/connector; see `concept-ownership.md`.
