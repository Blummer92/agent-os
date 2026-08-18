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

## Module/CLI execution path

`main(argv=None, *, bindings=None)` is the real entrypoint `__main__` calls, so
`python3 -m agent_os_execution_service.governed_resume_entrypoint "$@"` (what the
installed wrapper runs) genuinely parses argv, reconstructs, and dispatches at
most once instead of silently completing as a no-op. Argv parsing (and its
rejection of anything other than one canonical `--handoff-id`) still runs before
`bindings.reconstruct` is ever called.

`build_governed_resume_bindings(...)` composes the real
`reconstruct_governed_invocation` (#1218) and `run_single_issue_pilot` (#758/#1253)
functions -- imported directly, never duplicated -- into the single-argument
`GovernedResumeBindings` shape this module requires. Every argument it takes
(descriptor loader, current-evidence resolver, lease reader, lease/workspace/
executor/validator adapters, cancellation probe) is an existing canonical
protocol implementation supplied by the caller; this function performs no
reconstruction or dispatch logic of its own and invents no adapter.

Concrete production instances of those adapters (real descriptor storage,
GitHub-backed current-evidence readers, host-local lease/workspace/executor
adapters) are host composition, not part of this repository-only slice -- see
"Remaining risks" on the linked pull request. Run with no `bindings` supplied,
`main()` uses a fail-closed stand-in that raises before any dispatch could
occur, so the installed host command can no longer exit successfully without
attempting governed resume.

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
