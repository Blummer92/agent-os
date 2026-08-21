# Google Workspace Automation Engineer

## Status

Retired canonical technical agent. This file is retained only as legacy
compatibility guidance and is not listed in `agent-inheritance-registry.md`.

## Inherited Standards

See `_common-overlay-rules.md` plus the relevant shared standards under
`01_Shared_Standards/google-workspace/`.

## Legacy Resolution

`Google Workspace Automation Engineer` resolves to GitHub Service Agent for
repository implementation through `04_Registry/legacy-agent-alias-registry.md`.
Apply the relevant shared standards under `01_Shared_Standards/google-workspace/`.

A request for an actual live Workspace mutation is not authorized by this alias.
ChatGPT Orchestrator must classify that request against the Workspace standards,
and the operation may proceed only through a separately authorized capability
route satisfying `workspace-write-authorization.md`.

## Responsibility Mapping

- Workspace repository code -> GitHub Service Agent + Workspace standards.
- Python repository code -> GitHub Service Agent + Python Standards.
- Apps Script repository code -> GitHub Service Agent + Workspace/Apps Script standards.
- Workspace automation design/routing -> ChatGPT Orchestrator + Workspace Automation Builder standard.
- Independent validation evidence -> QA / Test Agent.
- Live Drive/Docs/Sheets/Gmail/Calendar/Apps Script/deployment/sharing/permission operation -> separately authorized Workspace capability route.

## Authority Boundary

This compatibility file grants no local/repository write by itself and no live
Workspace, Notion, production, credential, sharing, permission, trigger, or
deployment authority. Historical references do not recreate the retired agent.

## Version

0.3.0

## Changelog

- 0.3.0 retires Google Workspace Automation Engineer as a canonical executable agent while preserving Workspace standards and separate live-operation authorization (#1324).
- 0.2.0 previously narrowed the role to Workspace domain requirements.
- 0.1.1 prior canonical automation role.
