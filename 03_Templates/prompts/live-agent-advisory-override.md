# Live Agent Advisory Override

Use this prompt at the top of a live agent task when Agent OS is in Advisory Mode but the agent is still pausing on low-risk work.

```text
Use Agent OS Advisory Mode with low-risk local output.

This is Tier 0/Tier 1 work.

Proceed with a local draft, plan, review, or report.

If scope is unclear, state assumptions and continue with safe local output.

Pause only if the task requires:
- external writes
- production changes
- governed fields
- source-of-truth updates
- sharing or permission changes
- deletion or overwrite
- sensitive student/private data
- irreversible actions
```

## Candy Branding Example

```text
@Digital Media Unit Alignment Planner

Use Agent OS Advisory Mode with low-risk local output.

This is Tier 1 local planning/drafting work.

Proceed with candy branding alignment as a local draft.

No external writes.
No production changes.
No governed fields.
No source-of-truth updates.
No sharing or permission changes.
No sensitive student/private data.
No irreversible actions.

If scope is unclear, state assumptions and continue with safe local output.

Output:
- candy brand concept
- target audience
- visual style direction
- slogan/tagline ideas
- packaging ideas
- alignment to digital media standards
- student deliverables
```

## Notes

This override does not weaken safety gates. It only clarifies that low-risk read-only or local-only work should proceed as safe local output.
