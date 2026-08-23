# Workspace Write Authorization

## Purpose

Govern any live Google Workspace mutation independently from repository
implementation ownership or legacy agent names.

## Required Authorization Evidence

Before any Drive, Docs, Sheets, Slides, Gmail, Calendar, Apps Script, trigger,
deployment, sharing, permission, or related Workspace write:

- confirm the exact target file/folder/document/sheet/script/calendar/message destination;
- confirm the exact operation and affected range/property/content when applicable;
- confirm the live system of record and current target state;
- confirm the artifact/system owner and required approval;
- confirm the credential/scope boundary without exposing secrets;
- confirm rollback, disable, or reconciliation behavior appropriate to the operation;
- stop on stale, conflicting, ambiguous, or incomplete evidence.

## Agent And Capability Boundary

Google Workspace is a capability domain, not a canonical executable technical
agent. ChatGPT Orchestrator may route a separately authorized Workspace operation
to an available approved connector/capability. Repository implementation of the
supporting code belongs to GitHub Service Agent.

Repository implementation authorization, a passing test, a legacy `Google
Workspace Automation Engineer` alias, or successful routing never grants a
Workspace write.

## Prohibited Implications

No authorization to write one Workspace target implies permission to:

- broaden sharing or permissions;
- deploy or create triggers;
- mutate another Workspace product or target;
- modify production/master/template records beyond the exact approved operation;
- write Notion or GitHub;
- retain or expose credentials.

## Version

0.2.0

## Changelog

- 0.2.0 makes Workspace write authorization agent-independent while preserving exact-target, owner, scope, rollback, and fail-closed gates after retirement of the Workspace-specific canonical agent (#1324).
- 0.1.0 initial exact-target rule.
