# Source Context Response Module

## Name

Source Context

## Purpose

Show where a response was grounded without turning a short answer into a long audit trail.

This module connects modular response patterns to Notion, Google Drive, GitHub, Sheets, and other approved source systems. It describes evidence context only; it does not decide source authority or grant write permission.

## Status

experimental

## Default Fields

Use the smallest useful version.

```text
Source checked:
Status:
Authority:
Live verification needed before:
```

## Field Guidance

| Field | Use |
|---|---|
| Source checked | Name the system or document consulted, such as Notion cached index, live Notion, GitHub file, Drive folder, or Sheet. |
| Status | Use `cached`, `live-verified`, `not verified`, or `not checked`. |
| Authority | Use `source of truth`, `routing aid`, `working context`, or `supporting evidence`. |
| Live verification needed before | Name any action that requires live verification, such as readiness/status changes, writes, production authorization, ownership changes, sharing changes, or governed-field decisions. |

## Short Form

Use this when the source note must stay very small.

```text
Source Context: Notion cached index; routing aid; live verification needed before readiness or production decisions.
```

## Full Form

Use this when the user is comparing sources, asking for deep research, or making a decision that could affect governed fields.

```text
Source checked: Notion cached index and GitHub standard.
Status: cached, not live-verified.
Authority: Notion index is a routing aid; GitHub standard governs Agent OS behavior.
Live verification needed before: readiness/status changes, ownership decisions, production authorization, or governed-field edits.
```

## When To Use

- The answer depends on Notion, Drive, Sheets, GitHub, or another connected source.
- The user asks where an answer came from.
- The answer uses cached or indirect source information.
- The task involves source authority, readiness, routing, or production safety.

## When Not To Use

- The answer is pure drafting, wording, or brainstorming with no source claim.
- The user asks for a quick opinion and no source was checked.
- The response is already a required implementation or review report with its own evidence section.

## Notion Connection

For Notion-grounded answers, this module references the existing Notion source path rather than redefining it:

1. `01_Shared_Standards/notion/notion-navigation-index-standard.md`
2. `08_Tooling/notion-navigation-client/docs/registry-fit.md`
3. `08_Tooling/notion-navigation-client/docs/source-registry.md`

The response module only reports source context. It does not replace the Notion Navigation Index Standard, the Notion navigation client boundary, or the Digital Media source registry.

## Guardrails

- Do not treat cached Notion information as live verification.
- Do not use this module as authorization to write.
- Do not promote working context into source of truth.
- Do not duplicate Notion authority tables in response pattern files.
- Keep the source note short unless the user asks for audit-level detail.

## Feedback Notes

```text
Did the source context make the answer more trustworthy?
Was it short enough?
Did it avoid turning the response into an audit report?
What field was missing or unnecessary?
Keep / revise / reject:
```
