# Concept Ownership Matrix

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth; the canonical document named in each row is authoritative. **Manual Version 1 —
> should eventually be generated** from repository metadata. The same data is mirrored in
> `metadata.yaml` under `concepts`.

Use this before adding a new document: find the concept, confirm its canonical owner,
and extend at the recommended location instead of creating a parallel authority.

| Concept | Canonical document | Owner | Duplicate risk | Extension location |
|---|---|---|---|---|
| Source of truth | `AGENTS.md`; `00_Governance/ownership-and-source-of-truth.md` | GitHub Service Agent | High | governance only |
| Write authorization | `00_Governance/write-authorization-policy.md` | GitHub Service Agent | High | governance, or overlay exception |
| Agent routing | `04_Registry/agent-inheritance-registry.md`; `04_Registry/responsibility-matrix.md` | Integration Manager | High | registry files |
| Navigation Registry purpose | `01_Shared_Standards/navigation/navigation-registry-standard.md` | Integration Manager | High | same standard |
| Registry schema | `navigation-registry-architecture.md`; `navigation-registry-data-model.md` | Integration Manager | Medium | data model for entity/field changes |
| Relationships | `navigation-registry-data-model.md` (types); `navigation-registry-architecture.md` (traversal) | Integration Manager | Medium | data model for types |
| Aliases | `navigation-registry-data-model.md`; `04_Registry/legacy-agent-alias-registry.md` | Integration Manager | Medium | data model or registry for data |
| Connector framework | `connector-adapter-framework.md` | Integration Manager | High | connector framework only |
| Workspace discovery | `workspace-discovery-service.md` | Integration Manager | Medium | discovery service doc |
| Notion navigation | `notion-navigation-index-standard.md` | Integration Manager | Medium | Notion standard or client docs |
| Drive navigation | navigation standards + future Drive adapter spec | Integration Manager / Google Workspace Automation Engineer | Medium | adapter spec, not new core model |
| GitHub navigation | navigation standards + `02_Agent_Overlays/github-service-agent.md` | GitHub Service Agent | Medium | adapter spec or GitHub overlay |
| Testing | Python testing standards + `tests/` + `07_Agent_Tests/` | QA / Test Agent | Medium | test standards and fixtures |
| Benchmarking / compute metrics | Issue #97 planning until implemented | QA / Test Agent | Medium | test framework docs |
| Agent handoffs | `03_Templates/prompts/github-change-request.md` (GitHub); future handoff standard if approved | Integration Manager / GitHub Service Agent | Medium | shared handoff standard if a gap remains |
| Instructional quality | instructional-design standards + instructional overlays | Agent Orchestrator / instructional agents | Medium | instructional shared standard, not navigation docs |
| Visual assets / Prompt Library | Notion working knowledge unless promoted; Issue #97 dependency | Instructional Materials Coach / Integration Manager | Medium | Notion handoff or registry metadata, not GitHub content storage |
| DMSC integration | Issue #97 dependency until an adapter contract exists | Integration Manager | Medium | adapter/dependency spec; separate-repo changes need a separate request |

## Concepts that should not get a new document

- A second Navigation Registry architecture or a second connector framework.
- A new agent for a content domain (photography, typography, graphic design) unless the
  registry proves a repeatable role — see `00_Governance/agent-creation-policy.md`.
- A GitHub classroom-artifact repository without explicit approval (see `AGENTS.md`).
