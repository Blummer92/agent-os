# Alias And Deprecation Map

- Retire `Workspace Automation Builder` as a standalone agent name.
- Route automation design/build tasks to Google Workspace Automation Engineer.
- Route scoped implementation tasks to Workspace Implementation Overlay.
- Do not create a new agent unless it has unique ownership, write surfaces, and stop conditions.
- Do not create `Dashboard Sync Agent` as a standalone canonical agent.
- Treat `Dashboard Sync Agent` as a non-canonical routed alias for dashboard sync workflows.
- Route default dashboard sync work to Integration Manager with Dashboard Builder Overlay and Apps Script Sync Test Overlay.
- Route governance-heavy dashboard sync work to Modeling & Dashboard Governance Agent with Dashboard Builder Overlay.
- Route implementation-heavy dashboard sync work to Google Workspace Automation Engineer with Workspace Implementation Overlay and Apps Script Sync Test Overlay.
- Route validation-heavy dashboard sync work to QA / Test Agent with Apps Script Sync Test Overlay.
- Retire `Apps Script Sync Test Agent` as a standalone canonical agent name; retain Apps Script Sync Test Overlay as specialist sync-validation behavior.
