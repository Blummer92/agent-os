# Agent OS Codespaces Runbook — `agent-os-codespaces-v1`

Operator guide for issue #891's first persistent Agent OS execution profile
(design approved in #857). Config: `.devcontainer/devcontainer.json`,
`.devcontainer/post-create.sh`, `scripts/agent-os-environment-health.py`.

## Create the Codespace

From `Blummer92/agent-os`, on `main`: GitHub UI → **Code → Codespaces →
Create codespace on main**. This repo's config always requests the 2-core
Linux machine type (`hostRequirements.cpus: 2`); do not pick a larger type.

## Bootstrap and dependency identity

`postCreateCommand` runs `.devcontainer/post-create.sh` once: it verifies
repository identity (`Blummer92/agent-os`) before installing anything, then
installs exactly `requirements-dev.txt` plus the editable `08_Tooling`
packages the Agent OS Validation Gate already installs — no extra or
substituted dependencies. A failing step stops the script (`set -euo
pipefail`); the Codespace itself stays up for inspection since a failed
`postCreateCommand` does not tear down the container.

## Environment health check

Run `python3 scripts/agent-os-environment-health.py` any time. It prints one
bounded JSON evidence object and exits `0` only if every check passes:
repository identity, exact `HEAD` SHA/branch and primary-vs-issue-worktree
role, `git`/`python`/`pip`/`gh` versions, free disk space, presence of the
required validation entrypoints, and GitHub-auth capability. It never prints
credential values, and any prohibited-credential pattern found in its own
output is redacted and the run fails closed.

## Network modes

- **`local-only`** (default, `AGENT_OS_NETWORK_MODE`): an Agent OS
  application-level operating mode, not a firewall — it does not prevent
  network access, and the Codespace may still reach configured package
  indexes during bootstrap. No GitHub or external-system operation is
  automatically authorized in this mode.
- **`github-connected`**: permits only bounded GitHub fetch/branch/push/
  Draft-PR/metadata operations, only when separately authorized through the
  GitHub Service Agent overlay; no automatic mode switching. Neither mode
  grants merge, issue-closure, production, credential, or external-write
  authority.

## Issue-worktree preparation (#807, reused)

Use `scripts/prepare-issue-worktree.sh` unmodified for isolated per-issue
worktrees (see `scripts/prepare-issue-worktree.md`). The primary checkout can
never be reused as an issue worktree — already enforced and tested by
`tests/test_prepare_issue_worktree.py::test_target_path_containing_the_primary_checkout_is_rejected`.

## Stop/start, disconnect, and process persistence

Repository and worktree files on the Codespace's persistent disk survive a
browser disconnect and a stop/start cycle. **Running processes do not** —
anything started in a terminal (servers, long validations) stops when the
Codespace stops and must be restarted after resume; never assume otherwise.

## Validation budgets

Declared budgets: focused validation 15 min, aggregate validation 45 min,
single command 20 min, 256 KiB retained stdout/stderr each. Run
`./scripts/validate-all.sh` for the aggregate suite. Observed bootstrap time,
aggregate validation duration, and peak disk use must be measured on first
real run and recorded before any larger budget or machine size is requested.

## Authentication boundaries

Only the Codespaces-issued GitHub token is available by default — no Google,
Notion, Microsoft, classroom, or other credential is loaded. The health check
reports auth *capability* only (boolean + source), never token contents, and
scans its own evidence for prohibited credential patterns before printing.

## Cost, idle timeout, and retention (operator actions)

Repository code cannot set personal Codespaces billing controls. The operator must independently set: idle timeout ≤ 30 minutes, one primary Agent OS
Codespace at a time, no prebuilds, stopped-environment retention ≤ 30 days;
review retained evidence after 14 days.

## Cleanup and rollback

Revert only `.devcontainer/`, `scripts/agent-os-environment-health.py`, the
two focused test files, this runbook, and the policy-required `CHANGELOG.md`
/ `04_Registry/module-version-map.md` entries — no force operations needed.
Deleting branches, worktrees, Codespaces, or credentials is a separate,
manual operator action, never automatic.

## Handoff to #858

This profile provides the persistent execution target; #858's
checkpoint/resume design should build on the stop/start file-persistence and
process-non-persistence behavior documented above rather than redefining it.

## Non-authorization

Bootstrap and health-check success never imply implementation, execution,
Ready-for-Review, merge, issue-closure, production, or external-write
authority. Every authority field this profile reports stays `false`.
