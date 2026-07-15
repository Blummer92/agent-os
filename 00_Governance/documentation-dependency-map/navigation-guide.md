# Documentation Navigation Guide

> Companion to `00_Governance/documentation-dependency-map.md`. Index, not a source of
> truth. These are human reading paths; the **machine-executable** form of the same
> paths lives in `metadata.yaml` under `reading_paths`, so an agent can eventually load
> and follow a path by name instead of re-searching.

Answer to "If I need to build or modify Agent OS, what do I read first?": pick the path
that matches your task and read the files in order. Every path starts from `AGENTS.md`.

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
4. relevant overlay + referenced shared standards
5. matching `07_Agent_Tests/<overlay>.tests.md`

### Navigation Registry implementation
1. `AGENTS.md`
2. `02_Agent_Overlays/integration-manager.md`
3. `01_Shared_Standards/navigation/README.md`
4. `navigation-registry-standard.md`
5. `navigation-registry-architecture.md`
6. `navigation-registry-data-model.md`
7. `connector-adapter-framework.md`
8. `workspace-discovery-service.md`
9. `tests/` fixtures and `07_Agent_Tests/`

### Notion integration
1. `AGENTS.md`
2. `01_Shared_Standards/notion/notion-navigation-index-standard.md`
3. `08_Tooling/notion-navigation-client/README.md`
4. `08_Tooling/notion-navigation-client/docs/registry-fit.md`
5. `01_Shared_Standards/navigation/connector-adapter-framework.md`

### Google Drive integration
1. `AGENTS.md`
2. `00_Governance/write-authorization-policy.md`
3. relevant Google Workspace or Integration Manager overlay
4. `01_Shared_Standards/navigation/connector-adapter-framework.md`
5. `01_Shared_Standards/navigation/navigation-registry-data-model.md`

### GitHub integration
1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. `02_Agent_Overlays/github-service-agent.md`
5. `03_Templates/prompts/github-change-request.md`

### Classroom artifact generation
1. `AGENTS.md`
2. `04_Registry/responsibility-matrix.md`
3. instructional overlay (Unit Alignment, Teacher Modeling, or Instructional Materials Coach)
4. referenced instructional-design standards
5. Notion handoff or source evidence, then approved Google Drive destination

### Testing
1. `AGENTS.md`
2. `04_Registry/responsibility-matrix.md`
3. `02_Agent_Overlays/qa-test-agent.md`
4. Python testing standards under `01_Shared_Standards/python/`
5. `tests/` and `07_Agent_Tests/`

### Governance
1. `AGENTS.md`
2. `00_Governance/ownership-and-source-of-truth.md`
3. `00_Governance/write-authorization-policy.md`
4. registry ownership files in `04_Registry/`

### Change Requests
1. `AGENTS.md`
2. `03_Templates/prompts/github-change-request.md`
3. owner overlay + affected standard or tooling docs
4. tests and validation evidence
