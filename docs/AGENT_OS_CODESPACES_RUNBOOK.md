# Agent OS Codespaces Runbook — `agent-os-codespaces-v1`

Operator guide for issue #891's persistent Agent OS execution profile
(design approved in #857), extended additively by #972 and #2307. Config:
`.devcontainer/devcontainer.json`, `.devcontainer/post-create.sh`, and
`scripts/agent-os-environment-health.py`.

## Create the Codespace

From `Blummer92/agent-os`, on the exact candidate branch or `main`: GitHub UI →
**Code → Codespaces → Create codespace**. This repo requests the 2-core Linux
machine type (`hostRequirements.cpus: 2`); do not pick a larger type without a
decision. After a devcontainer feature change, rebuild before treating the new
feature as current capability evidence.

## Bootstrap and dependency identity

`postCreateCommand` runs `.devcontainer/post-create.sh` once. It verifies the
repository before installing `requirements-dev.txt` and the same editable
`08_Tooling` packages used by validation. A failing step stops fail closed;
the Codespace remains available for inspection.

## Bounded CLI SSH access (#2307)

The profile includes the official Dev Container `sshd` feature so an
authenticated GitHub CLI client can use `gh codespace ssh` for bounded remote
commands. This is an execution-surface capability only: it grants no GitHub
write, merge, issue-closure, production, credential, lease-release, Scheduler,
or external-write authority and does not change `AGENT_OS_NETWORK_MODE`.

After creating or rebuilding the exact profile, the bounded health probe is:

```bash
gh codespace ssh -c <codespace> -- "cd /workspaces/agent-os && python3 scripts/agent-os-environment-health.py"
```

Closed PR #1215 remains historical qualification evidence. Its local Dockerfile
workaround for a then-stale inherited Yarn apt source is not part of #2307 unless
current Codespaces build evidence reproduces that failure. Do not add historical
base-image workarounds speculatively.

## Environment health check

Run `python3 scripts/agent-os-environment-health.py`. The existing v1 schema
includes current-attempt evidence: `execution_surface_id`, canonical UTC
`observed_at`, content-addressed `environment_health_evidence_id`, explicit
`process-execution`, bounded tool states, and GitHub-auth states. Existing
`available` / `capable` booleans remain present.

Evidence from another surface is not current-surface proof. The checker observes
only its governed terminal/runtime environment; it performs no tool install or
login.

## Network modes

- **`local-only`** (default, `AGENT_OS_NETWORK_MODE`) is an application-level
  mode, not a firewall. It grants no GitHub or external-system authority.
- **`github-connected`** permits bounded GitHub operations only when separately
  authorized through the GitHub Service Agent. It grants no merge, issue
  closure, production, credential, or external-write authority.

## Issue-worktree preparation (#807, reused)

Use `scripts/prepare-issue-worktree.sh` unmodified for isolated issue worktrees.
The primary checkout cannot be reused as an issue worktree.

## Stop/start, disconnect, and process persistence

Repository/worktree files survive browser disconnect and stop/start. Running
processes do not; restart terminal processes after resume. Process disappearance
on stop is not clean Scheduler termination evidence and never releases a lease.

## Validation budgets

Focused validation budget: 15 min; aggregate validation: 45 min; single command:
20 min; retained stdout/stderr: 256 KiB each. Run `./scripts/validate-all.sh` for
aggregate validation when the canonical validation plan requires it.

## Authentication boundaries (#1401)

Token presence alone never proves authentication. `local-only` makes no GitHub
network probe. `github-connected` uses the existing bounded direct GitHub probe;
no token or response is emitted.

## #918 compatibility boundary

Issue #918 consumes environment-health identity as opaque upstream evidence.
Codespaces SSH supplies process/transport capability evidence only; it does not
create a second executor route or substitute for GCE when #759 containment,
unattended Scheduler execution, fixed service identity, or another VM-only
capability is required.

## Cost, idle timeout, and retention (operator actions)

Repository code cannot set personal Codespaces billing controls. Independently
set idle timeout ≤ 30 minutes, keep one primary Agent OS Codespace at a time,
use no prebuilds, keep stopped-environment retention ≤ 30 days, and review
retained evidence after 14 days.

## Cleanup and rollback

Rollback #2307 by reverting the `sshd` feature and its bounded-access docs/tests.
Deleting branches, worktrees, Codespaces, or credentials remains a separate
operator action.

## Handoff to #858

The profile preserves #858 stop/start persistence and process-non-persistence
semantics; checkpoint/resume remains owned there rather than redefined here.

## Non-authorization

Health or SSH success never implies implementation, Ready-for-Review, merge,
issue closure, production, lease release, or external-write authority. Every
authority field reported by the profile remains `false`.
