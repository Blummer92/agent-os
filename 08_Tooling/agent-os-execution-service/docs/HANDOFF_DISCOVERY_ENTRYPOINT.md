# Handoff Discovery Host Entrypoint — #1284

Issue #1284 freezes the installed path as
`/usr/local/libexec/agent-os-handoff-discovery`.

The public argv contract is exactly:

```text
--repository <owner/name> --issue-number <positive integer>
```

Nothing else is accepted: no store root, path, handoff identity, branch, flag,
argument reordering, or extra token. The wrapper forwards argv unchanged and
evaluates no command text.

## Why this entrypoint exists

An execution interface such as ChatGPT can address a repository and an issue but
cannot read the canonical #1218 checkpoint store. Without this seam it falls back
to generic GitHub publish tooling, checks local `git`/`gh`, finds them missing,
and reports a false blocker. This entrypoint closes that gap by letting the
existing transport ask the trusted host one read-only question:

```text
repository + issue
-> canonical #1242 discover_issue_handoff(...)
-> found | not-found | needs-decision
```

## Store root is host composition

`AGENT_OS_CHECKPOINT_STORE_ROOT` is baked into the installed wrapper at install
time and reassigned unconditionally, so an inherited, SSH-forwarded, or
caller-supplied environment can never redirect the scan. An unset or blank value
returns `needs-decision` with `store-not-configured`; it never becomes a default
path to invent.

## Authority boundary

Discovery is a locator. It is not currentness and not authorization.

The entrypoint never creates or persists a handoff, chooses between multiple
descriptors, interprets prose or branch names, writes the store, acquires a
lease, invokes the Scheduler, or performs GitHub, network, cloud, merge, or
issue-closure effects. Every result carries `execution_authorized`,
`scheduler_invoked`, and `side_effects_performed` fixed false, including a
`found` result.

A `found` handoff is an existing immutable identity and nothing more. It must
still pass the existing #1218 reconstruction, current-evidence, source/scope,
checkpoint, ResumePlan, environment, and Scheduler lease checks before anything
executes. Discovery deliberately returns `needs-decision` rather than guessing
when several descriptors match, because currentness is downstream evidence and
must never be inferred from descriptor age, file order, or issue status.

## Module/CLI execution path

`main(argv=None)` is the real entrypoint `__main__` calls, so
`python3 -m agent_os_execution_service.handoff_discovery_entrypoint "$@"` (what
the installed wrapper runs) genuinely parses argv and calls the merged #1242
locator. `parse_discovery_argv(...)` rejects anything other than one canonical
repository/issue pair before the store is touched, so a malformed request never
becomes a scan.

The module imports `discover_issue_handoff` directly. It re-implements no
descriptor selection, matching, bounding, or integrity rule.

## Installation contract

`scripts/install-handoff-discovery` defaults to root:root mode `0755` at the
frozen path. Re-running with identical content is idempotent. It refuses
unrelated target names, relative store roots, and store roots containing `..` or
unsupported characters.

For offline installer tests, `TARGET`, `OWNER`, `GROUP`, `MODE`, and `STORE_ROOT`
may be set to a temporary controlled location. Production deployment must use the
frozen path and separately authorized host mutation.

Unlike the resume wrapper, this wrapper needs no delegated `systemd-run` scope:
it performs a bounded read and dispatches no execution.

## Rollback

Remove only `/usr/local/libexec/agent-os-handoff-discovery`. Do not delete or
alter checkpoint descriptors, ResumePlans, dependency-readiness evidence,
Scheduler leases, workspaces, or audit records. The resume entrypoint, canonical
store, transport, and Scheduler remain unchanged.

Actual installation on `agent-os-test`, IAM/WIF changes, production activation,
merge, and issue closure remain outside this repository slice.
