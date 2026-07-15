# GitHub Implementation Response Pattern

## Name

GitHub Implementation

## Purpose

Report repository implementation work in a compact, auditable format without burying the user in process detail.

## Status

experimental

## Default Modules

1. Scope
2. Files Changed
3. Tests Run
4. Blockers
5. Next Step

## Max Length Guidance

- Target: 5 short sections.
- Use concise bullets.
- Include required Agent OS reporting fields when the task is an implementation or review report.

## When To Use

- A GitHub change request has been executed.
- A branch, commit, or pull request was created.
- Repository files were changed.
- The user needs implementation status and handoff details.

## When Not To Use

- The user is only discussing an idea.
- No repository work occurred.
- The task is curriculum planning without GitHub changes.
- The user asks for deep research instead of implementation status.

## Example Response

**Scope**
Created an experimental response-pattern documentation branch. No code changed.

**Files Changed**
- `01_Shared_Standards/communication/response-pattern-registry.md`
- `01_Shared_Standards/communication/response-patterns/quick-decision.md`

**Tests Run**
Not run. Documentation-only change.

**Blockers**
No runtime blocker. Human review still needed before merge.

**Next Step**
Review the draft PR and test the patterns in daily Agent OS use before promoting them.

## Feedback Notes

```text
Was the implementation status clear?
Were required report fields present?
Was anything too verbose?
Keep / revise / reject:
```
