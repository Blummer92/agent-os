# Agent OS Codespaces Runbook — `agent-os-codespaces-v1`

Operator guide for the persistent Agent OS execution profile introduced by #891 and extended by #972. Config: `.devcontainer/devcontainer.json`, `.devcontainer/post-create.sh`, `scripts/agent-os-environment-health.py`.

## Create the Codespace

From `Blummer92/agent-os`, on `main`: GitHub UI → **Code → Codespaces → Create codespace on main**. This repo's config requests the 2-core Linux machine type; do not select a larger type without a separate decision.

## Environment health check

Run `python3 scripts/agent-os-environment-health.py` any time. It prints one bounded JSON evidence object and exits `0` only if every required check passes. The v1 profile remains compatible while exposing additive current-attempt evidence:

- `execution_surface_id` — bounded identity of the governed runtime surface, defaulting to `agent-os-codespaces-v1`;
- `observed_at` — canonical UTC observation time;
- `environment_health_evidence_id` — content-addressed SHA-256 identity of material evidence (observation time excluded so an unchanged observation retains identity);
- explicit `process-execution` state proven by a bounded child-process check;
- tool `state` values `available`, `unavailable`, or `unknown`, with bounded version evidence, while retaining the existing `available` boolean;
- GitHub-auth `state` values `authenticated`, `unauthenticated`, `unknown`, or `not-applicable` while retaining the existing `capable` boolean and source.

Use `--execution-surface-id <id>` or `AGENT_OS_EXECUTION_SURFACE_ID` only for the current governed runtime. Evidence from a different surface is not current-surface proof and must fail closed in consumers. This is runtime evidence, not a persistent host inventory.

The checker never probes ChatGPT connectors, browsers, Google Drive, Notion, or provider applications. Those capabilities belong to their owning interaction/integration surfaces. It never prints credential values; prohibited credential patterns found in its own evidence are redacted and fail closed.

## Network modes

- **`local-only`** (default): application-level operating mode, not a firewall. No GitHub or external-system operation is automatically authorized.
- **`github-connected`**: permits only bounded GitHub operations when separately authorized through the GitHub Service Agent overlay. It does not create authentication or authority.

Neither mode grants merge, issue closure, production, credential, or external-write authority.

## Issue-worktree preparation (#807, reused)

Use `scripts/prepare-issue-worktree.sh` for isolated per-issue worktrees. The health report preserves exact checkout SHA/branch and primary-vs-issue-worktree evidence.

## Stop/start and process persistence (#858 handoff)

Repository and worktree files on persistent Codespaces storage survive browser disconnects and stop/start cycles. Running terminal processes do not; restart them after resume. The `process-execution` check proves only that the current observation can create a bounded child process.

## Authentication boundaries

Only existing runtime GitHub authentication is observed. Environment token presence is reported as `authenticated` / `env` without token contents. `gh auth status` may establish `authenticated` or `unauthenticated`; execution failure/timeout is `unknown`; no `gh` executable is `not-applicable`. The checker never logs in, creates credentials, or broadens network access.

## Issue #918 compatibility boundary

Issue `#918` may consume `environment_health_evidence_id` as opaque upstream evidence and compare the supplied `execution_surface_id` before selecting a route. #972 does not implement executor routing. In particular, ChatGPT connector availability cannot be substituted for proof that a runtime has process execution, a `gh` executable, or authenticated CLI state.

## Validation

Run the focused tests first:

```bash
python -m pytest -q tests/test_agent_os_environment_health.py
python -m pytest -q tests/test_agent_os_environment_contract.py
python -m compileall -q scripts/agent-os-environment-health.py
```

Then run `./scripts/validate-all.sh` and the current repository structure checks. Validation success is evidence only and creates no implementation or merge authority.

## Cost, idle timeout, and retention

Keep the existing 2-core profile, idle timeout and retention controls unless a separately governed decision changes them. This evidence extension does not alter Codespaces billing, retention, or machine-size policy.

## Cleanup and rollback

Revert the #972 changes to `scripts/agent-os-environment-health.py`, focused environment-health tests, and this runbook. The extension creates no external state, schema migration, connector registration, credential, Scheduler state, or persistent environment inventory.

## Non-authorization

Bootstrap and health-check success never imply implementation, execution, Ready-for-Review, merge, issue closure, production, or external-write authority. Every authority field reported by this profile remains `false`.
