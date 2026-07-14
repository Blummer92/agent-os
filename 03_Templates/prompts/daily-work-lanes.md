# Daily Work Lanes

Use this prompt when common classroom or planning work should move quickly while
preserving strict gates for high-risk writes.

This prompt operates under `00_Governance/agent-os-advisory-mode.md` and does
not override `00_Governance/write-authorization-policy.md`.

## Core Rule

Route internally unless the task is blocked, the user asks for routing details,
or the request enters Red Lane.

For Green and Yellow Lane work, show only:
- selected lane
- selected path
- output
- blockers
- next action

Do not expose full overlay, registry, or handoff mechanics unless needed.

## Green Lane - Read-Only / Drafting

Use for brainstorming, lesson drafts, planning, summaries, QA notes, local specs,
and local documentation.

Behavior:
- Proceed after lightweight intake.
- Route internally.
- Do not expose full routing unless blocked.
- Do not write to external systems.

## Yellow Lane - Workspace Output

Use for Drive, Docs, Slides, worksheets, Notion handoffs, generated classroom
materials, image-prep plans, and classroom file organization.

Behavior:
- Confirm target folder or handoff destination before external writes.
- Use approved templates and source context when available.
- Report generated assets, QA status, and remaining risks.
- Do not modify sharing, permissions, governed fields, or source-of-truth records
  unless explicitly approved.

## Red Lane - Governance / Source-of-Truth

Use for GitHub, standards, overlays, registries, templates, tests, release notes,
governed fields, production writes, or irreversible changes.

Behavior:
- Require explicit authorization.
- Use `03_Templates/prompts/github-change-request.md` when repository changes are
  needed.
- Route GitHub writes only through the GitHub Service Agent.
- Use a non-main branch and draft pull request.

## Example

Teacher request: "Build tomorrow's Photography lesson."

Expected behavior:
- Select Yellow Lane if Drive or Notion output is requested.
- Select Green Lane if the output is only a draft plan.
- Route through the curriculum pipeline internally.
- Ask only for missing target folders or handoff destinations before external
  writes.
- Do not route classroom artifacts to GitHub unless explicitly approved.
