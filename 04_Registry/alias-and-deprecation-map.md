# Alias And Deprecation Map

## Retired Canonical Technical Roles

- Retire `Integration Manager` as a canonical executable agent.
  - Legacy name resolves to ChatGPT Orchestrator.
  - Cross-system routing, source-of-truth checks, Navigation Registry governance,
    reusable-capability governance, dependency checks, and compatibility decisions
    remain shared standards/capabilities consumed by ChatGPT Orchestrator.
  - Repository implementation resulting from those decisions routes to GitHub
    Service Agent.

- Retire `Google Workspace Automation Engineer` as a canonical executable agent.
  - Legacy implementation-oriented name resolves to GitHub Service Agent plus
    Google Workspace standards.
  - Workspace external-operation classification is routed by ChatGPT Orchestrator
    under the Workspace authorization standards.
  - The legacy alias grants no Drive, Docs, Sheets, Gmail, Calendar, Apps Script,
    sharing, permission, deployment, or production write authority.

- Retire `Python Development Overlay` as an executable-agent-like implementation
  identity.
  - Retain the overlay file only as compatibility guidance.
  - Route Python repository implementation to GitHub Service Agent plus
    `01_Shared_Standards/python/`.

## Previously Retired Names

- `Workspace Automation Builder` remains a workflow/standard name, not an agent.
- `Dashboard Sync Agent` remains non-canonical; route by job type.
- `Apps Script Sync Test Agent` remains retired; `Apps Script Sync Test Overlay`
  is specialist validation guidance, not an executable agent.

## Current Technical Routing

- repository engineering -> GitHub Service Agent
- independent validation/evidence -> QA / Test Agent
- cross-system/source-of-truth/capability routing -> ChatGPT Orchestrator + standards
- Workspace/Apps Script technical constraints -> shared standards/capability overlays
- dashboard governance -> Modeling & Dashboard Governance Agent
- dashboard repository implementation -> GitHub Service Agent
- dashboard validation evidence -> QA / Test Agent

Do not create a new agent unless it has a unique repeatable job, ownership
boundary, write surface, and stop conditions that cannot be represented through a
retained canonical agent plus shared standards/capabilities.
