# Agent OS Codespaces Runbook — `agent-os-codespaces-v1`

Operator guide for issue #891's persistent Agent OS execution profile
(design approved in #857), extended additively by #972. Config:
`.devcontainer/devcontainer.json`, `.devcontainer/post-create.sh`, and
`scripts/agent-os-environment-health.py`.

## Create the Codespace

From `Blummer92/agent-os`, on `main`: GitHub UI → **Code → Codespaces →
Create codespace on main**. This repo requests the 2-core Linux machine type
(`hostRequirements.cpus: 2`); do not pick a larger type without a decision.

## Bootstrap and dependency identity

`postCreateCommand` runs `.devcontainer/post-create.sh` once. It verifies the
repository before installing `requirements-dev.txt` and the same editable
`08_Tooling` packages used by validation. A failing step stops fail closed;
the Codespace remains available for inspection.

## Environment health check

Run `python3 scripts/agent-os-environment-health.py`. The existing v1 schema
remains backward compatible and now adds current-attempt evidence:
`execution_surface_id`, canonical UTC `observed_at`, content-addressed
`environment_health_evidence_id`, explicit `process-execution`, tool
`available|unavailable|unknown` states, and GitHub-auth states
`authenticated|unauthenticated|unknown|no-credential|not-applicable`.
Existing `available` / `capable` booleans remain present.

The evidence ID binds the complete redacted observation, including surface and
observation time. Evidence from another surface is not current-surface proof.
`AGENT_OS_EXECUTION_SURFACE_ID` may explicitly name the governed surface;
Codespaces otherwise use `CODESPACE_NAME`, with a bounded opaque local fallback.

The checker observes only its governed terminal/runtime environment: no
ChatGPT connector, browser, Drive, Notion probing; no tool install or login.

## Network modes

- **`local-only`** (default, `AGENT_OS_NETWORK_MODE`) is an application-level
  mode, not a firewall. It grants no GitHub or external-system authority.
- **`github-connected`** permits bounded GitHub operations only when separately
  authorized through the GitHub Service Agent. It grants no merge, issue
  closure, production, credential, or external-write authority.

## Issue-worktree preparation (#807, reused)

Use `scripts/prepare-issue-worktree.sh` unmodified for isolated issue
worktrees. The primary checkout cannot be reused as an issue worktree.

## Stop/start, disconnect, and process persistence

Repository/worktree files survive browser disconnect and stop/start. Running
processes do not; restart terminal processes after resume.

## Validation budgets

Focused validation budget: 15 min; aggregate validation: 45 min; single
command: 20 min; retained stdout/stderr: 256 KiB each. Run
`./scripts/validate-all.sh` for aggregate validation.

## Authentication boundaries (#1401)

Token presence alone never proves authentication. `local-only` makes no
GitHub network probe (`not-applicable`). `github-connected` makes exactly one
bounded, read-only, direct GitHub API read via `GITHUB_TOKEN`/`GH_TOKEN` --
distinct from generic connector/CLI evidence, the #1363 root cause. Success
proves `authenticated`; a missing credential is `no-credential`; `401`/`403`/
network error/timeout fail closed. No retry; no token or response is emitted.

## #918 compatibility boundary

Issue #918 consumes environment-health identity only as opaque upstream
evidence and does not probe capabilities or implement routing here. Connector
access never substitutes for required process execution or a real `gh`.

## Cost, idle timeout, and retention (operator actions)

Repository code cannot set personal Codespaces billing controls. Independently
set idle timeout ≤ 30 minutes, keep one primary Agent OS Codespace at a time,
use no prebuilds, keep stopped-environment retention ≤ 30 days, and review
retained evidence after 14 days.

## Cleanup and rollback

Rollback is a normal repository revert of the #972 changes. Deleting branches,
worktrees, Codespaces, or credentials remains a separate manual operator action.

## Handoff to #858

The profile preserves #858 stop/start persistence and process-non-persistence
semantics; checkpoint/resume remains owned there rather than redefined here.

## Non-authorization

Health success never implies implementation, execution, Ready-for-Review,
merge, issue closure, production, or external-write authority. Every authority
field reported by the profile remains `false`.
