# Agent OS Codespaces Runbook — `agent-os-codespaces-v1`

Operator guide for issue #891's persistent Agent OS execution profile
(design approved in #857), extended additively by #972 and #1212. Config:
`.devcontainer/devcontainer.json`, `.devcontainer/Dockerfile`,
`.devcontainer/post-create.sh`, and `scripts/agent-os-environment-health.py`.

## Create the Codespace

From `Blummer92/agent-os`, on `main`: GitHub UI → **Code → Codespaces →
Create codespace on main**. This repo requests the 2-core Linux machine type
(`hostRequirements.cpus: 2`); do not pick a larger type without a decision.

## Base image preparation and bootstrap

The local `.devcontainer/Dockerfile` inherits the existing Python 3.11 Bookworm
Dev Container image and removes only its stale Yarn apt source before Dev
Container features run. #1212 added this bounded preparation after live
Codespaces creation evidence showed the official `sshd` feature's `apt-get
update` failing on that inherited source with `NO_PUBKEY 62D54FD4003F6525`,
which caused Codespaces to start its Alpine recovery container. Agent OS does
not add a replacement Yarn key or package source and does not treat the recovery
container as a supported execution runtime.

`postCreateCommand` then runs `.devcontainer/post-create.sh` once. It verifies
the repository before installing `requirements-dev.txt` and the same editable
`08_Tooling` packages used by validation. A failing step stops fail closed; the
Codespace remains available for inspection.

## Bounded CLI SSH access (#1212)

The profile includes the official Dev Container `sshd` feature so an authenticated
GitHub CLI client can use `gh codespace ssh` for bounded remote commands. This is
an access capability only: it does not grant implementation, GitHub-write,
provider, production, lease-release, or lifecycle authority, and it does not
change `AGENT_OS_NETWORK_MODE`.

After changing devcontainer features or base preparation, rebuild the Codespace
before treating the feature as present. A bounded health probe from an authorized
client is:

```bash
gh codespace ssh -c <codespace> -- "cd /workspaces/agent-os && python3 scripts/agent-os-environment-health.py"
```

SSH availability is execution-surface capability evidence, not proof that the
Codespace satisfies Workflow Scheduler containment, lease, checkpoint, or
stop/start requirements. Those remain separately qualified under #1212.

## Environment health check

Run `python3 scripts/agent-os-environment-health.py`. The existing v1 schema
remains backward compatible and now adds current-attempt evidence:
`execution_surface_id`, canonical UTC `observed_at`, content-addressed
`environment_health_evidence_id`, explicit `process-execution`, tool
`available|unavailable|unknown` states, and GitHub-auth
`authenticated|unauthenticated|unknown|not-applicable` states. Existing
`available` / `capable` booleans remain present.

The evidence ID binds the complete redacted observation, including surface and
observation time. Evidence from another surface is not current-surface proof.
`AGENT_OS_EXECUTION_SURFACE_ID` may explicitly name the governed surface;
Codespaces otherwise use `CODESPACE_NAME`, with a bounded opaque local fallback.

The checker observes only its governed terminal/runtime environment. It does
not probe ChatGPT connectors, browsers, Google Drive, Notion, or application
providers, and it never installs tools or logs in.

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
processes do not; restart terminal processes after resume. Process disappearance
caused by Codespaces stop is not by itself clean-termination evidence and must
never authorize lease release or orphan recovery.

## Validation budgets

Focused validation budget: 15 min; aggregate validation: 45 min; single
command: 20 min; retained stdout/stderr: 256 KiB each. Run
`./scripts/validate-all.sh` for aggregate validation.

## Authentication boundaries

Existing environment-token presence may prove `authenticated` with source
`env` without revealing token contents. `gh auth status` may prove
`authenticated` or `unauthenticated`. Missing `gh` or an unobservable auth
probe fails closed to `unknown`. No token or credential value is emitted.

## #918 compatibility boundary

Issue #918 consumes environment-health identity only as opaque upstream evidence.
Issue #972 does not probe capabilities for #918 and does not implement routing.
Connector access never substitutes for required process execution, a real
`gh` executable, or authenticated CLI evidence.

## Cost, idle timeout, and retention (operator actions)

Repository code cannot set personal Codespaces billing controls. Independently
set idle timeout ≤ 30 minutes, keep one primary Agent OS Codespace at a time,
use no prebuilds, keep stopped-environment retention ≤ 30 days, and review
retained evidence after 14 days.

## Cleanup and rollback

Rollback for #1212 is a normal repository revert removing the bounded Dockerfile
preparation, restoring the direct image declaration, removing the `sshd` feature,
and reverting its bounded-access documentation. Deleting branches, worktrees,
Codespaces, or credentials remains a separate manual operator action.

## Handoff to #858

The profile preserves #858 stop/start persistence and process-non-persistence
semantics; checkpoint/resume remains owned there rather than redefined here.

## Non-authorization

Health or SSH success never implies implementation, execution, Ready-for-Review,
merge, issue closure, production, lease release, or external-write authority.
Every authority field reported by the profile remains `false`.
