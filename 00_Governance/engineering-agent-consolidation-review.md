# Engineering Agent Consolidation Review

## Decision

Retire overlapping technical agent identities and route work by repeatable job.
Technical subject matter remains shared standards, helper overlays, capability
contracts, or provider contracts unless a distinct executable job is proven.

## Canonical Technical Execution Roles

- **GitHub Service Agent** — all authorized repository engineering and GitHub delivery.
- **QA / Test Agent** — independent validation, regression, acceptance, and release evidence.

## Retired Technical Roles

- `Integration Manager` — retired as a canonical executable agent. Cross-system,
  source-of-truth, navigation, reusable-capability, dependency, and compatibility
  routing now belongs to ChatGPT Orchestrator consuming the corresponding shared
  standards. Repository implementation routes to GitHub Service Agent.
- `Google Workspace Automation Engineer` — retired as a canonical executable
  agent. Workspace design/runtime/write constraints live in Google Workspace
  standards and capability overlays. Repository implementation routes to GitHub
  Service Agent; external Workspace mutations remain separately authorized.
- `Python Development Overlay` — compatibility guidance only. Python is a shared
  technical standard, not an agent-selection criterion.
- `Apps Script Sync Test Agent` — remains retired; the helper overlay remains
  validation guidance.
- `Dashboard Sync Agent` — remains non-canonical; route by governance,
  implementation, validation, or cross-system routing job.

## Routing

- Repository implementation: GitHub Service Agent.
- Independent verification and release evidence: QA / Test Agent.
- Cross-system/source-of-truth/capability routing: ChatGPT Orchestrator + shared standards.
- Workspace/Apps Script requirements: shared standards/capabilities.
- Workspace/Apps Script repository code: GitHub Service Agent.
- Workspace live operation: separately authorized capability route under Workspace write rules.
- Dashboard governance: Modeling & Dashboard Governance Agent.
- Dashboard implementation: GitHub Service Agent.
- Dashboard validation: QA / Test Agent.

## Safety Boundary

Retirement does not transfer external-write authority. Repository implementation
authorization never implies permission to mutate Drive, Docs, Sheets, Gmail,
Calendar, Apps Script deployments/triggers, Notion, production systems, sharing,
or permissions.

## Result

Before #1324, the canonical registry contains 10 agents and four technical
execution roles (GitHub Service Agent, Google Workspace Automation Engineer,
Integration Manager, QA / Test Agent). After #1324, the registry contains eight
canonical agents and two technical execution roles (GitHub Service Agent and QA /
Test Agent).
