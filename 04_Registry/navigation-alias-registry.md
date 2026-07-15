# Navigation Alias Registry

## Purpose

This file maps stable human-readable aliases to common Agent OS reading paths so agents can find governed documentation without repeated manual searches.

Aliases are lookup aids only. They do not change source-of-truth ownership, grant write authority, replace live verification, or duplicate inherited policy text. Apply the referenced source files for the governing rules.

## Registry Governance

The Navigation Alias Registry is the authoritative source for alias definitions and alias behavior.

Alias governance inherits existing Agent OS rules instead of creating new governance:

- Ownership is defined by `04_Registry/responsibility-matrix.md` and `01_Shared_Standards/navigation/navigation-registry-standard.md`.
- Source-of-truth boundaries are defined by `00_Governance/ownership-and-source-of-truth.md` and `01_Shared_Standards/navigation/navigation-registry-standard.md`.
- Write authorization is defined by `00_Governance/write-authorization-policy.md`.

Aliases must reference existing governed documentation paths. They do not override overlay inheritance, source-of-truth rules, or write authorization.

## Alias Design Guidelines

- Use concise, stable names.
- Avoid duplicate aliases.
- Avoid overlapping aliases.
- Prefer references over copied policy.
- Keep aliases task-oriented.
- Keep reading paths deterministic.

## Validation

Every file path listed in an alias must exist in the repository. Missing paths block automatic alias use and require Navigation Alias Registry review before the alias is used.

## Starter Aliases

### @governance-start

| Field | Value |
|---|---|
| Alias | `@governance-start` |
| Purpose | Used when an agent needs the basic source-of-truth and write authorization rules. |
| Owner | ChatGPT Orchestrator |
| Source of truth | GitHub Agent OS governance files |
| Files to read in order | 1. `AGENTS.md`<br>2. `00_Governance/ownership-and-source-of-truth.md`<br>3. `00_Governance/write-authorization-policy.md` |
| Stop condition | Stop after the system of record and write boundary are clear; if authorization or source of truth is unclear, stop and ask. |

### @agent-routing

| Field | Value |
|---|---|
| Alias | `@agent-routing` |
| Purpose | Used when an agent needs to identify the correct task owner and overlay. |
| Owner | ChatGPT Orchestrator |
| Source of truth | Agent OS registry files in GitHub |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/legacy-agent-alias-registry.md`<br>3. `04_Registry/agent-inheritance-registry.md`<br>4. `04_Registry/responsibility-matrix.md` |
| Stop condition | Stop after the canonical owner and overlay are identified; then read the selected overlay and referenced standards. If no owner is clear, recommend a registry update instead of inventing an agent. |

### @navigation-registry

| Field | Value |
|---|---|
| Alias | `@navigation-registry` |
| Purpose | Used when an agent is working on Navigation Registry governance, lookup routing, or related implementation. |
| Owner | Integration Manager |
| Source of truth | GitHub shared navigation standard and registry files |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/agent-inheritance-registry.md`<br>3. `04_Registry/responsibility-matrix.md`<br>4. `02_Agent_Overlays/integration-manager.md`<br>5. `01_Shared_Standards/navigation/navigation-registry-standard.md`<br>6. `00_Governance/documentation-dependency-map/navigation-guide.md` |
| Stop condition | Stop after navigation ownership, lookup scope, source-of-truth boundary, and write boundary are clear. Do not add automation, schema changes, or cache writes without explicit approval. |

### @github-change-request

| Field | Value |
|---|---|
| Alias | `@github-change-request` |
| Purpose | Used when a non-GitHub agent needs to prepare a repository change handoff. |
| Owner | GitHub Service Agent |
| Source of truth | GitHub Change Request template and GitHub Service Agent overlay |
| Files to read in order | 1. `AGENTS.md`<br>2. `00_Governance/ownership-and-source-of-truth.md`<br>3. `00_Governance/write-authorization-policy.md`<br>4. `02_Agent_Overlays/github-service-agent.md`<br>5. `03_Templates/prompts/github-change-request.md` |
| Stop condition | Stop after the handoff includes target repository, branch, files, owner, permissions needed, acceptance criteria, validation evidence, risks, and blockers. The handoff does not authorize non-GitHub agents to write to GitHub. |

### @classroom-artifact-routing

| Field | Value |
|---|---|
| Alias | `@classroom-artifact-routing` |
| Purpose | Used when deciding whether a lesson, slide deck, worksheet, or classroom artifact belongs in GitHub, Notion, or Google Drive. |
| Owner | Instructional Materials Coach |
| Source of truth | AGENTS.md destination rules and instructional materials overlay |
| Files to read in order | 1. `AGENTS.md`<br>2. `04_Registry/responsibility-matrix.md`<br>3. `02_Agent_Overlays/instructional-materials-coach.md`<br>4. `01_Shared_Standards/instructional-design/README.md` |
| Stop condition | Stop after the destination is clear: Agent OS governance artifacts default to GitHub, teacher planning and working knowledge default to Notion or a Notion handoff, and student-facing materials default to approved Google Drive folders. GitHub storage for classroom artifacts requires explicit approval and a GitHub Change Request handoff. |

## Version History

- Phase 3: aligned alias registry governance with existing Agent OS ownership, source-of-truth, and write authorization references.
