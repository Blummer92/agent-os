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

## Production host composition (#1287 / AOS-GCE2B)

`production_host_composition.build_production_governed_resume_bindings(...)`
supplies the smallest production wiring for the two adapters above.
`build_governed_resume_bindings` cannot be reused directly: it needs
`lease`/`workspace`/`executor`/`validator` eagerly, but those depend on the
`ConcreteRuntimeConfiguration` for the exact `pilot_input` reconstruction
admits, which is not known until after admission. So this module builds
`GovernedResumeBindings` directly: `reconstruct` is a `functools.partial` of
`reconstruct_governed_invocation` bound to production readers
(`HostCurrentInvocationSources`, `CanonicalCurrentInvocationResolver`,
`load_invocation_descriptor`); `dispatch` builds the concrete adapters via
`build_concrete_runtime_adapters` only once an admitted `pilot_input` exists,
then calls `run_single_issue_pilot` exactly once.

The checkpoint store root comes only from `AGENT_OS_CHECKPOINT_STORE_ROOT`
(no default, no caller override), matching the existing hook-adapter
convention. A host-local `lease_directory` is required; both the
reconstruction-time lease observation and the dispatch-time lease adapter use
`HostLocalLeaseAdapter` exclusively. If the runtime configuration bound to an
admitted pilot input would select any other lease directory (including
`None`, which selects `InMemoryLeaseAdapter`), dispatch fails closed instead.
No new Scheduler, lease, store, router, or transport system is introduced.

Installing that dependency graph on the qualified host -- which distribution owns
each module, the declared runtime dependencies, and the native Scheduler
extension build -- is `HOST_RUNTIME_INSTALLATION.md` (#1300 / AOS-GCE2C).
