# Agent Inheritance Registry

| Agent | Inherits | Overlay |
|---|---|---|
| Google Workspace Automation Engineer | Global, Python, Workspace, Notion | google-workspace-automation-engineer |
| Modeling & Dashboard Governance Agent | Global, Dashboard Governance, Notion | modeling-dashboard-governance-agent |
| Integration Manager | Global, Workspace, Notion | integration-manager |
| QA / Test Agent | Global, QA/Test | qa-test-agent |

## Routed Combinations

| Workflow | Canonical Owner | Overlays |
|---|---|---|
| Dashboard sync, default cross-system route | Integration Manager | Dashboard Builder Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, governance-heavy route | Modeling & Dashboard Governance Agent | Dashboard Builder Overlay |
| Dashboard sync, implementation-heavy route | Google Workspace Automation Engineer | Workspace Implementation Overlay; Apps Script Sync Test Overlay |
| Dashboard sync, validation-heavy route | QA / Test Agent | Apps Script Sync Test Overlay |
