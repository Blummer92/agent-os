# Engineering Agent Consolidation Review

## Decision
Retire overlapping agent names and route work to canonical roles plus overlays.

## Routing
- Automation design/build: Google Workspace Automation Engineer.
- Scoped implementation: Workspace Implementation Overlay.
- Dashboard governance: Modeling & Dashboard Governance Agent.
- Verification and release evidence: QA / Test Agent.
- Dashboard sync: route by dominant work type instead of creating a standalone Dashboard Sync Agent.
- Default dashboard sync route: Integration Manager with Dashboard Builder Overlay and Apps Script Sync Test Overlay.
- Apps Script Sync Test Agent is retired as a standalone canonical agent; Apps Script Sync Test Overlay remains active specialist behavior.
