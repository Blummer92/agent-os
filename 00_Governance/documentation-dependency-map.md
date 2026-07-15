# Agent OS Documentation Dependency Map

## Purpose

This guide is the entry point for understanding how Agent OS documentation fits together before implementation work begins. It helps contributors and agents find canonical documents, avoid duplicate documentation, and choose the correct extension point.

It does not replace any governed standard. It maps existing governance, standards, overlays, registries, tooling docs, tests, and implementation planning artifacts so future work can reuse them.

## Scope

This guide covers Agent OS documentation discovery for:

- governance and source-of-truth rules
- registered agent ownership and overlays
- Navigation Registry standards
- Notion navigation standards and tooling
- connector and discovery standards
- tests and fixtures
- classroom artifact routing
- GitHub Change Requests

Notion and Google Drive content remain live working surfaces. This document does not move classroom artifacts into GitHub and does not authorize writes to Notion, Drive, Sheets, or any production system.

## Canonical Start Path

Read in this order unless a narrower task clearly needs less context:

1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. `04_Registry/agent-inheritance-registry.md`
5. `04_Registry/responsibility-matrix.md`
6. the relevant file in `02_Agent_Overlays/`
7. any shared standards referenced by that overlay
8. any relevant tooling README or test documentation

This preserves the existing Agent OS rule to read only the files needed for the task.

## Documentation Inventory

| File path | Purpose | Owner | Source of truth | Audience | Status | Action | Duplicate-risk notes |
|---|---|---|---|---|---|---|---|
| `AGENTS.md` | ChatGPT entry point, global source-of-truth and access rules. | GitHub Service Agent | GitHub | all agents, contributors | Active | Reuse | Do not duplicate global source-of-truth or access rules elsewhere. |
| `00_Governance/ownership-and-source-of-truth.md` | Defines system-of-record and inheritance-first documentation policy. | GitHub Service Agent | GitHub | contributors, all agents | Active | Reuse | Shared rules live once here or in shared standards. |
| `00_Governance/write-authorization-policy.md` | Defines read-only default and write authorization checks. | GitHub Service Agent | GitHub | all agents | Active | Reuse | Do not restate write policy in overlays except as agent-specific exceptions. |
| `04_Registry/agent-inheritance-registry.md` | Lists canonical agents, inheritance, overlays, and routed combinations. | Integration Manager | GitHub | agents, routing workflows | Active | Reuse | Agent aliases must resolve here or through alias registry. |
| `04_Registry/responsibility-matrix.md` | Maps responsibilities to primary and support agents. | Integration Manager | GitHub | routing, handoffs | Active | Reuse | Use this before creating a new agent or assigning ownership. |
| `02_Agent_Overlays/integration-manager.md` | Defines Integration Manager scope for cross-system routing and navigation governance. | Integration Manager | GitHub | Integration Manager, GitHub Service Agent | Active | Reuse / Extend only for Integration Manager-specific exceptions | Do not repeat shared Navigation Registry rules here. |
| `01_Shared_Standards/navigation/README.md` | Index and reading order for the Navigation Registry documentation stack. | Integration Manager | GitHub | Navigation Registry implementers | Active | Reuse | This already owns the navigation-standard reading order. |
| `01_Shared_Standards/navigation/navigation-registry-standard.md` | Governing standard for cross-system lookup boundaries. | Integration Manager | GitHub | all registry consumers | Active | Reuse | Canonical source for registry purpose, ownership, and write boundary. |
| `01_Shared_Standards/navigation/navigation-registry-architecture.md` | Implementation-independent registry schemas and workflows. | Integration Manager | GitHub | implementers, QA | Active | Reuse / Extend | Do not create a second architecture document. |
| `01_Shared_Standards/navigation/navigation-registry-data-model.md` | Canonical platform-independent data contract. | Integration Manager | GitHub | implementers, connector owners | Active | Reuse / Extend | Core entity or field changes belong here. |
| `01_Shared_Standards/navigation/connector-adapter-framework.md` | Platform-independent connector contract. | Integration Manager | GitHub | connector implementers | Active | Reuse | Do not create new connector frameworks for individual systems. |
| `01_Shared_Standards/navigation/workspace-discovery-service.md` | Discovery, validation, drift classification, and recommendation model. | Integration Manager | GitHub | QA, connector owners | Active | Reuse / Extend | Discovery recommends; it does not modify live systems by default. |
| `01_Shared_Standards/notion/notion-navigation-index-standard.md` | Notion-specific cached navigation-index standard. | Integration Manager | GitHub | Notion navigation consumers | Active | Reuse | Keep Notion-specific cache behavior here, not in general registry docs. |
| `08_Tooling/notion-navigation-client/README.md` | Read-only Notion navigation-index client documentation. | Google Workspace Automation Engineer / Integration Manager | GitHub | tooling users, QA | Active | Reuse / Extend tooling docs only | This is a Notion adapter/client, not the full Navigation Registry. |
| `08_Tooling/notion-navigation-client/docs/registry-fit.md` | Explains how the Notion client fits the broader Navigation Registry. | Integration Manager | GitHub | implementers | Active | Reuse | Update when adapter expectations change. |
| `tests/` | Python and registry fixture tests. | QA / Test Agent | GitHub | QA, implementers | Active | Extend | New navigation workflow tests should add fixtures here or a governed equivalent path. |
| `03_Templates/prompts/github-change-request.md` | Handoff template for repository changes. | GitHub Service Agent | GitHub | non-GitHub agents needing repo changes | Active | Reuse | Do not invent new GitHub handoff formats without approval. |
| GitHub issues `#97` and `#98` | Planning and documentation-map work items. | Integration Manager / GitHub Service Agent | GitHub issue tracker | implementers, reviewers | Active planning | Reference | Issue content informs implementation but does not replace governed docs. |

## Documentation Dependency Graph

```text
AGENTS.md
  -> 00_Governance/ownership-and-source-of-truth.md
  -> 00_Governance/write-authorization-policy.md
  -> 04_Registry/agent-inheritance-registry.md
  -> 04_Registry/responsibility-matrix.md
  -> 02_Agent_Overlays/<selected-owner>.md
     -> 01_Shared_Standards/<referenced-standard>.md
        -> 08_Tooling/<tool>/README.md when implementation exists
        -> tests/ and fixtures when validation exists
        -> GitHub Change Request or issue when new work is needed
```

Navigation-specific dependency path:

```text
AGENTS.md
  -> ownership-and-source-of-truth.md
  -> write-authorization-policy.md
  -> responsibility-matrix.md
  -> integration-manager.md
  -> 01_Shared_Standards/navigation/README.md
     -> navigation-registry-standard.md
     -> navigation-registry-architecture.md
     -> navigation-registry-data-model.md
     -> connector-adapter-framework.md
     -> workspace-discovery-service.md
  -> 01_Shared_Standards/notion/notion-navigation-index-standard.md
  -> 08_Tooling/notion-navigation-client/README.md
  -> tests/fixtures and validation suites
```

## Documentation Navigation Guide

### New contributor

1. `README.md`
2. `AGENTS.md`
3. `00_Governance/ownership-and-source-of-truth.md`
4. `04_Registry/responsibility-matrix.md`
5. relevant overlay in `02_Agent_Overlays/`

### Agent developer

1. `AGENTS.md`
2. `04_Registry/agent-inheritance-registry.md`
3. `04_Registry/responsibility-matrix.md`
4. relevant overlay
5. referenced shared standards
6. test standards and fixtures for the target tool or agent

### Navigation Registry implementation

1. `AGENTS.md`
2. `02_Agent_Overlays/integration-manager.md`
3. `01_Shared_Standards/navigation/README.md`
4. `navigation-registry-standard.md`
5. `navigation-registry-architecture.md`
6. `navigation-registry-data-model.md`
7. `connector-adapter-framework.md`
8. `workspace-discovery-service.md`
9. `tests/fixtures/` and related QA docs

### Notion integration

1. `AGENTS.md`
2. `01_Shared_Standards/notion/notion-navigation-index-standard.md`
3. `08_Tooling/notion-navigation-client/README.md`
4. `08_Tooling/notion-navigation-client/docs/registry-fit.md`
5. `01_Shared_Standards/navigation/connector-adapter-framework.md`
6. `01_Shared_Standards/navigation/workspace-discovery-service.md`

### Google Drive integration

1. `AGENTS.md`
2. `00_Governance/write-authorization-policy.md`
3. relevant Google Workspace or Integration Manager overlay
4. `01_Shared_Standards/navigation/connector-adapter-framework.md`
5. `01_Shared_Standards/navigation/navigation-registry-data-model.md`
6. relevant Drive tooling docs or fixtures

### GitHub integration

1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. GitHub Service Agent overlay if present
5. `03_Templates/prompts/github-change-request.md`
6. relevant standards, tests, and PR review docs

### Classroom artifact generation

1. `AGENTS.md`
2. `04_Registry/responsibility-matrix.md`
3. instructional agent overlay, such as Unit Alignment Agent, Teacher Modeling Coach, or Instructional Materials Coach
4. referenced instructional design standards
5. Notion handoff or source evidence
6. approved Google Drive artifact destination

### Testing

1. `AGENTS.md`
2. `04_Registry/responsibility-matrix.md`
3. QA / Test Agent overlay if present
4. Python testing standards under `01_Shared_Standards/python/`
5. `tests/` and `07_Agent_Tests/`
6. workflow-specific fixtures

### Governance

1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. registry ownership files in `04_Registry/`
5. relevant shared standards

### Change Requests

1. `AGENTS.md`
2. `03_Templates/prompts/github-change-request.md`
3. owner overlay
4. affected standard or tooling docs
5. tests and validation evidence

## Concept Ownership Matrix

| Concept | Canonical document | Related documents | Owner | Duplicate risk | Extension location |
|---|---|---|---|---|---|
| Source of truth | `AGENTS.md`; `00_Governance/ownership-and-source-of-truth.md` | shared standards | GitHub Service Agent | High | governance only |
| Write authorization | `00_Governance/write-authorization-policy.md` | overlays for exceptions | GitHub Service Agent | High | governance or specific overlay exception |
| Agent routing | `04_Registry/agent-inheritance-registry.md`; `04_Registry/responsibility-matrix.md` | overlays | Integration Manager | High | registry files |
| Navigation Registry purpose | `navigation-registry-standard.md` | navigation README | Integration Manager | High | same standard |
| Registry schema | `navigation-registry-architecture.md`; `navigation-registry-data-model.md` | connector framework | Integration Manager | Medium | data model for field/entity changes |
| Relationships | `navigation-registry-architecture.md`; `navigation-registry-data-model.md` | workspace discovery | Integration Manager | Medium | data model for types; architecture for traversal behavior |
| Aliases | `navigation-registry-data-model.md` | legacy alias registry | Integration Manager | Medium | data model or `04_Registry/` for data |
| Connector framework | `connector-adapter-framework.md` | workspace discovery | Integration Manager | High | connector framework only |
| Workspace discovery | `workspace-discovery-service.md` | connector framework, data model | Integration Manager | Medium | discovery service doc |
| Notion navigation | `notion-navigation-index-standard.md` | notion-navigation-client docs | Integration Manager | Medium | Notion standard or client docs |
| Drive navigation | navigation standards and future Drive adapter spec | Google Workspace overlay | Integration Manager / Google Workspace Automation Engineer | Medium | adapter spec, not new core model |
| GitHub navigation | navigation standards plus GitHub Service Agent rules | GitHub Change Request template | GitHub Service Agent | Medium | adapter spec or GitHub overlay |
| Testing | Python testing standards and `tests/` | QA overlay | QA / Test Agent | Medium | test standards and fixture directories |
| Benchmarking | Issue #97 planning until implemented | testing docs | QA / Test Agent | Medium | test framework docs |
| Compute metrics | Issue #97 planning until implemented | testing docs | QA / Test Agent | Medium | test framework docs |
| Agent handoffs | `03_Templates/prompts/github-change-request.md` for GitHub; future handoff standard if approved | overlays | Integration Manager / GitHub Service Agent | Medium | shared handoff standard if gap remains |
| Instructional quality | instructional design standards and instructional overlays | classroom workflows | Agent Orchestrator / instructional agents | Medium | instructional shared standard, not navigation docs |
| Visual assets | Notion working knowledge, Drive artifacts, DMSC sync dependency | Issue #97 | Instructional Materials Coach / Integration Manager | Medium | dependency interface or Notion handoff, not GitHub content storage |
| Prompt Library | Notion working knowledge unless promoted | Issue #97 | Instructional Materials Coach / Integration Manager | Medium | Notion handoff or registry metadata only |
| DMSC integration | Issue #97 dependency until adapter contract exists | connector framework | Integration Manager | Medium | adapter/dependency spec, separate repo changes require separate request |

## Gap Analysis

### Missing or partial documentation

- A formal agent-to-agent handoff standard beyond GitHub Change Requests is still partial.
- Navigation workflow regression tests and benchmark fixtures are planned but not yet formalized.
- Compute-efficiency metrics for agent workflows are planned in Issue #97 but not yet canonical.
- Google Drive and GitHub adapter specs for the Navigation Registry are not yet present as system-specific specs.
- Instructional quality rubrics for cognitive load, task analysis, grade-level language, misconception alignment, and visual/icon density are not yet mapped to test fixtures.
- DMSC image/icon sync integration is a dependency interface, not a governed adapter spec yet.

### Duplicated or high-risk concepts

- Source-of-truth and write-boundary text should not be repeated in every overlay.
- Navigation architecture should not be recreated outside `01_Shared_Standards/navigation/`.
- Connector behavior should not be redefined per connector; adapters should inherit the framework.
- Notion cache behavior should stay in the Notion navigation index standard and client docs.

### Documentation that should not be created without proof

- A second Navigation Registry architecture.
- A second connector framework.
- A new agent for content domains such as photography, typography, or graphic design unless the registry proves a repeatable role.
- A GitHub classroom-artifact repository without explicit approval.

## Documentation Quality Review

| Area | Current strength | Improvement needed |
|---|---|---|
| Governance | Clear source-of-truth and write-boundary rules. | More cross-links from README to this guide. |
| Navigation standards | Strong ordered stack and authority map. | More implementation examples and adapter-specific examples. |
| Notion tooling | Clear read-only safety boundary. | Live-sheet drift validation remains a known limitation. |
| Testing | Existing Python test structure is present. | Navigation workflow tests and compute metrics need formal fixtures. |
| Classroom workflow docs | Agent responsibilities exist. | Handoff formats and instructional quality rubrics need consolidation. |

## Documentation Lifecycle Recommendation

Use this lifecycle for governed documentation:

```text
Draft -> Review -> Approved -> Implemented -> Maintained
Draft -> Archived
Approved -> Deprecated -> Archived
Implemented -> Deprecated -> Archived
```

Definitions:

- Draft: proposed content, not binding.
- Review: under QA or owner review.
- Approved: governed rule or design accepted.
- Implemented: supported by tooling, tests, or active usage.
- Maintained: current and actively referenced.
- Deprecated: replaced but retained for transition context.
- Archived: no longer active; retained for history.

Ownership transitions must identify the primary owner, supporting owner, source of truth, and rollback or archive path.

## Documentation Index Recommendation

Agent OS should keep a lightweight top-level index rather than duplicate every standard in the root README.

Recommended structure:

- `README.md`: short repository overview and link to `AGENTS.md` plus this documentation map.
- `AGENTS.md`: execution entry point and global routing.
- `00_Governance/documentation-dependency-map.md`: documentation discovery, dependency graph, and reading paths.
- folder-level `README.md` files: local order and canonical authority maps, such as the existing navigation standards README.

## Documentation Search Optimization Plan

| Recommendation | Expected effect | Safe boundary |
|---|---|---|
| Add a root README link to this guide. | Reduces first-hop search cost. | Does not move canonical rules. |
| Keep folder-level README authority maps. | Helps contributors find local canonical docs. | README indexes reference standards rather than restating them. |
| Add stable headings for concepts like Source Of Truth, Write Boundary, Owner, and Tests. | Improves search and citation precision. | Heading changes should preserve existing content. |
| Use concept ownership matrix before adding new docs. | Reduces duplicate standards. | Matrix is advisory; governed docs remain authoritative. |
| Treat failed agent runs as future test candidates. | Creates regression coverage without over-planning. | Tests must avoid duplicating live Notion or Drive content. |

## Documentation Metrics

Recommended metrics:

| Metric | Definition | Initial target |
|---|---|---|
| Documentation discoverability | Number of reads needed to find the canonical owner for a concept. | Three or fewer after using this guide. |
| Duplicate documentation rate | Concepts with more than one conflicting canonical document divided by reviewed concepts. | 0 conflicting canonical docs. |
| Orphan document rate | Documents with no inbound reference or clear owner divided by reviewed docs. | Below 10% after cleanup. |
| Documentation coverage | Required concepts with at least one canonical owner divided by required concepts. | 95% for active implementation areas. |
| Broken reference count | Referenced file paths that cannot be found. | 0 in active docs. |
| Average retrieval depth | Average dependency hops before reaching implementation instructions. | Reduce over time. |
| Documentation reuse rate | New work items that extend existing docs rather than creating new docs. | Increase over time. |

## Future Growth Strategy

- Add new connectors through adapter specs that inherit the connector framework.
- Add new agents only when the registry proves a repeatable role that existing agents cannot own.
- Keep classroom planning and readiness in Notion unless governance changes the source of truth.
- Keep student-facing artifacts in approved Google Drive folders unless explicitly approved otherwise.
- Add tests for every recurring agent failure, ambiguous navigation path, incomplete library, or source-of-truth conflict.
- Prefer indexes, cross-links, and extension notes over duplicate standards.

## Implementation Notes For Issue #98

This guide satisfies the first implementation pass for Issue #98 by creating:

1. a documentation inventory,
2. a dependency graph,
3. reading paths,
4. a concept ownership matrix,
5. gap and duplicate-risk notes,
6. documentation metrics, and
7. a future growth strategy.

Follow-up work should validate the inventory against the full repository tree and add automated checks for broken references and orphan documents.

## Version

0.1.0
