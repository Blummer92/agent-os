# Review Report Response Pattern

## Name

Review Report

## Purpose

Summarize review, validation, or audit work in a way that makes status, evidence, blockers, and next steps easy to see.

## Status

experimental

## Default Modules

1. Review Scope
2. Verdict
3. Evidence Checked
4. Issues Found
5. Tests Run
6. Next Step

## Max Length Guidance

- Target: 6 short sections.
- Lead with the verdict.
- Separate confirmed facts from risks or assumptions.
- Include required Agent OS final-report fields when applicable.

## When To Use

- Reviewing a pull request, document, workflow, lesson, or artifact.
- Validating whether work is complete.
- Reporting blockers or risks.
- Comparing expected behavior against evidence.

## When Not To Use

- The user only needs a fast recommendation.
- The user asks for a brainstorm.
- The user asks for a full implementation.
- The review has not inspected any evidence.

## Example Response

**Review Scope**
Reviewed the documentation-only response-pattern branch.

**Verdict**
Ready for human review. Not ready to promote to stable.

**Evidence Checked**
- Registry file exists.
- Five pattern files exist.
- Each pattern includes required fields.

**Issues Found**
No blocking documentation issue found.

**Tests Run**
Not run. Documentation-only review.

**Next Step**
Merge only after confirming the pattern names and daily iteration loop match user expectations.

## Feedback Notes

```text
Was the verdict clear enough?
Could I tell what evidence was actually checked?
Were blockers separated from risks?
Keep / revise / reject:
```
