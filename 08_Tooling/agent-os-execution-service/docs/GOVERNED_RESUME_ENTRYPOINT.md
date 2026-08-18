# Governed Resume Host Entrypoint

Issue #1238 freezes the installed path as `/usr/local/libexec/agent-os-governed-resume`.

The public argv contract is exactly:

```text
--handoff-id executor-handoff:<64-lowercase-hex>
```

The installed wrapper supplies the already-qualified delegated topology:
`systemd-run --user --scope -p Delegate=yes`. It forwards argv unchanged to the
Python entrypoint and never evaluates command text.

`run_governed_resume(...)` first calls the existing #1218/#1253 reconstruction
composition supplied by the host binding. Only an `admitted` result carrying a
current `pilot_input` may be passed once to the existing Workflow Scheduler
dispatch boundary. Blocked, stale, ambiguous, malformed, or incomplete results
perform zero dispatches.

The entrypoint is not a Scheduler, lease owner, retry loop, queue, state store,
authorization source, provider selector, or shell-command interface. Currentness,
authorization, checkpoint/ResumePlan, dependency readiness, and lease truth stay
with their existing canonical owners.

## Installation contract

The installer defaults to root:root mode `0755` at the frozen path. Re-running
with identical content is idempotent. It refuses unrelated target names and uses
`install` rather than broad recursive mutation.

For offline installer tests, `TARGET`, `OWNER`, `GROUP`, and `MODE` may be set to
a temporary controlled location. Production deployment must use the frozen path
and separately authorized host mutation.

## Rollback

Remove only `/usr/local/libexec/agent-os-governed-resume`. Do not delete or alter
checkpoint descriptors, ResumePlans, dependency-readiness evidence, Scheduler
leases, workspaces, or audit records.

Actual installation/verification on `agent-os-test`, SSH/IAP use, IAM/WIF,
workflow changes, production activation, merge, and issue closure remain outside
this repository-only slice.
