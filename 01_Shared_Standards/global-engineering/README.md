# Global Engineering Standards

- Global engineering rules apply to every coding and automation agent.
- `reusable-capability-registry-standard.md` governs reusable capability discovery, evidence, ownership, lifecycle, and report-only validation.

## Continuous Governed Execution

Treat a transition between registered Agent OS owners as internal routing, not by
itself as a user-visible handoff or stop. When the current user authorization,
source of truth, bounded scope, and evidence still cover the downstream action,
route to the responsible registered owner and continue in the same interaction.

Preserve every ownership boundary: the responsible owner still performs or owns
its governed work, including GitHub Service Agent repository writes and QA / Test
Agent validation evidence. Internal routing never transfers or creates authority.

Stop and surface the decision when authorization, source of truth, bounded scope,
or a material architecture, schema, compatibility, ownership, authority, external
effect, protected setting, production surface, or irreversible action changes.
The excluded surfaces in `../github/excluded-surface-baseline.md` remain separately
authorized.

Conversation continuity is not authorization. Phrases such as `continue`,
`next step`, and `keep going` may continue only actions already covered by current
authority; they never authorize a previously excluded surface.

For successful routine work, prefer one consolidated user-facing result over
serial copy/paste handoff prompts. Preserve handoff artifacts internally when a
canonical downstream owner or audit trail requires them.

## Mobile Terminal And Cloud Shell UX

When Zachary is using a mobile terminal or Cloud Shell, provide the fastest safe route as one copy-and-paste command whenever practical.

- Give a brief natural-language explanation immediately before the command.
- Combine dependent shell operations with `&&` or an equivalently fail-closed construction.
- Detect common setup states where practical, including a missing repository directory, wrong working directory, missing local branch, remote branch fetch, inactive virtual environment, and optional tool authentication.
- Minimize command fragmentation and keep commands readable on narrow mobile displays.
- Do not present shell prompts, terminal output, heredoc continuation prompts such as `>`, incomplete heredocs, or Python source directly as Bash commands.
- Use multiple commands only when operator input is required between steps, separate authorization is required, a potentially destructive operation requires inspection first, or combining steps would materially reduce auditability.
- Preserve all authorization, repository verification, protected-branch, destructive-action, and stop-condition safeguards.

## Version
0.4.0
