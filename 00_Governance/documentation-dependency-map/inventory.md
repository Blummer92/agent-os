# Documentation Inventory

> Companion to `00_Governance/documentation-dependency-map.md`. This is an index, not a
> source of truth; canonical rules live in the referenced files. **Manual Version 1 —
> the long-term goal is to generate this table automatically from repository structure
> and file metadata** (front matter, headings, registry entries) so it cannot drift.

Status values: Active, Draft, Planned, Deprecated. Action values: Reuse, Extend,
Replace, Archive.

| File path | Purpose | Owner | Source of truth | Audience | Status | Action | Duplicate-risk |
|---|---|---|---|---|---|---|---|
| `AGENTS.md` | Entry point; global source-of-truth and access rules. | GitHub Service Agent | GitHub | all agents, contributors | Active | Reuse | High — do not restate global source-of-truth/access rules elsewhere. |
| `00_Governance/ownership-and-source-of-truth.md` | System-of-record and inheritance-first documentation policy. | GitHub Service Agent | GitHub | contributors, all agents | Active | Reuse | High — shared rules live once here or in shared standards. |
| `00_Governance/write-authorization-policy.md` | Read-only default and write authorization checks. | GitHub Service Agent | GitHub | all agents | Active | Reuse | High — restate only as agent-specific exceptions in overlays. |
| `04_Registry/agent-inheritance-registry.md` | Canonical agents, inheritance, overlays, routed combinations. | Integration Manager | GitHub | agents, routing | Active | Reuse | High — aliases must resolve here or via alias registry. |
| `04_Registry/responsibility-matrix.md` | Responsibilities mapped to primary/support agents. | Integration Manager | GitHub | routing, handoffs | Active | Reuse | Medium — check before assigning ownership. |
| `02_Agent_Overlays/integration-manager.md` | Integration Manager scope for cross-system routing and navigation governance. | Integration Manager | GitHub | Integration Manager, GitHub Service Agent | Active | Extend (IM-specific only) | Medium — do not repeat shared navigation rules. |
| `02_Agent_Overlays/github-service-agent.md` | GitHub write executor scope and boundaries. | GitHub Service Agent | GitHub | GitHub Service Agent | Active | Reuse | Medium — GitHub write policy lives here + governance. |
| `01_Shared_Standards/navigation/README.md` | Index and reading order for the navigation stack. | Integration Manager | GitHub | Navigation implementers | Active | Reuse | Medium — already owns navigation reading order. |
| `01_Shared_Standards/navigation/navigation-registry-standard.md` | Governing standard for cross-system lookup boundaries. | Integration Manager | GitHub | registry consumers | Active | Reuse | High — canonical for registry purpose and write boundary. |
| `01_Shared_Standards/navigation/navigation-registry-architecture.md` | Registry schemas and workflows. | Integration Manager | GitHub | implementers, QA | Active | Extend | Medium — do not create a second architecture doc. |
| `01_Shared_Standards/navigation/navigation-registry-data-model.md` | Platform-independent data contract. | Integration Manager | GitHub | implementers, connectors | Active | Extend | Medium — entity/field changes belong here. |
| `01_Shared_Standards/navigation/connector-adapter-framework.md` | Platform-independent connector contract. | Integration Manager | GitHub | connector implementers | Active | Reuse | High — do not fork per-system connector frameworks. |
| `01_Shared_Standards/navigation/workspace-discovery-service.md` | Discovery, drift classification, recommendations. | Integration Manager | GitHub | QA, connectors | Active | Extend | Medium — discovery recommends; it does not modify live systems. |
| `01_Shared_Standards/notion/notion-navigation-index-standard.md` | Notion-specific cached navigation-index standard. | Integration Manager | GitHub | Notion navigation consumers | Active | Reuse | Medium — keep Notion cache behavior here. |
| `08_Tooling/notion-navigation-client/README.md` | Read-only Notion navigation-index client. | Google Workspace Automation Engineer / Integration Manager | GitHub | tooling users, QA | Active | Extend (tooling docs) | Medium — a Notion adapter, not the full registry. |
| `08_Tooling/notion-navigation-client/docs/registry-fit.md` | How the Notion client fits the broader registry. | Integration Manager | GitHub | implementers | Active | Reuse | Low. |
| `03_Templates/prompts/github-change-request.md` | Handoff template for repository changes. | GitHub Service Agent | GitHub | non-GitHub agents | Active | Reuse | Medium — do not invent new GitHub handoff formats. |
| `07_Agent_Tests/` | Overlay compliance tests and `validate-repo-structure.sh`. | QA / Test Agent | GitHub | QA, implementers | Active | Extend | Low — add new structural checks here, not a parallel runner. |
| GitHub issues `#97`, `#98` | Navigation plan and documentation-map work items. | Integration Manager / GitHub Service Agent | GitHub issue tracker | implementers, reviewers | Active planning | Reference | Low — issues inform work; they do not replace governed docs. |

## Coverage note

This table currently seeds the governance, navigation, Notion-tooling, handoff, and test
surfaces most relevant to Issue #97/#98. A generated inventory should eventually cover
the full repository tree; see `coverage-validation.md`.
