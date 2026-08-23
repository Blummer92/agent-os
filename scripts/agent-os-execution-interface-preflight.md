# Execution-interface governed-route preflight (#1237 / #1330)

## Failures removed

```text
work on an Agent OS issue -> generic GitHub publish tooling selected first
-> local `gh` prerequisite checked -> `gh` absent -> false blocker
```

and, for #1330:

```text
already-authorized exact repository operation
-> #918 says zero runtime capabilities are required
-> execution interface nevertheless routes through a runtime surface
```

Hard invariant: missing local `gh` != Agent OS execution unavailable. Local CLI
prerequisites apply only after a local CLI surface has actually been selected.

## Integration surface

Claude Code exposes repository-owned hooks that run before the model selects any
tool. `.claude/settings.json` in this repository wires two of them to
`scripts/agent-os-execution-interface-preflight.py`:

- `UserPromptSubmit` — runs on every submitted request, before tool selection;
- `PreToolUse` (matcher `Bash`) — runs before a shell command executes.

This is the concrete pre-tool routing hook #1237 required. It is repository
configuration, so it lives with the contract it enforces.

The #1330 zero-runtime consumer is
`scripts/agent_os_execution_interface/connector_native_fast_track.py`. It runs
only after upstream classification has already produced a valid #918
`ExecutorRouteDecision` for the exact next operation. It never parses prompt
text, infers capabilities from diff size, or selects a route itself.

## Zero-runtime fast-track (#1330)

```text
already-authorized exact operation
-> canonical #918 ExecutorRouteDecision
-> chatgpt-connector-native
-> connector_native_fast_track.consume_executor_route_decision(...)
-> use connected GitHub API surface
-> GitHub Service Agent reacquires current head/blob/authorization before write
```

For this path the adapter requires current upstream execution and GitHub-write
authority, rejects merge or external-write authority, and reports that no local
CLI prerequisite, governed runner, Cloud Build, mutation, or side effect was
performed by the adapter itself. The adapter does not grant write authority;
the GitHub Service Agent remains the sole repository writer and retains its
existing exact-currentness checks before each mutation.

Any non-empty runtime capability is still decided by #918. A governed-runner or
explicit external-fallback route is returned as `delegate-selected-route`
unchanged; the fast-track consumer cannot convert it into connector-native work.
A #918 human-decision route remains `needs-decision`.

If a connector-native action later proves insufficient, the existing #1237
`scripts.agent_os_execution_interface.post_selection_continuation` seam owns the
same-lineage capability transition. #1330 adds no retry or continuation engine.

## Resolved governed-runner path (#1237)

```text
governed Agent OS checkout + resolved repository + exactly one issue key
-> existing #1237 read-only handoff discovery
-> exactly one valid descriptor
-> existing immutable executor-handoff:<sha256>
-> existing bounded `/agent-os resume <id>` ingress
-> existing GitHub -> WIF -> GCE transport, #1238 host entrypoint,
   #1218/#1253 reconstruction, existing Workflow Scheduler
```

## Governed-runner outcomes

| Condition | Status |
| --- | --- |
| exactly one matching descriptor | `governed-resume-available` + existing ingress |
| zero matching descriptors | `not-found`, bounded; no synthetic identity |
| multiple matching descriptors | `needs-decision`; no `latest` heuristic |
| corrupt / unavailable / over-bound store | `needs-decision`, fail closed |
| descriptor store not configured | `needs-decision`, fail closed |
| multiple distinct issue keys | `needs-decision`; never picks one |
| governed checkout, repository unresolved | `needs-decision`, fail closed |
| non-governed checkout, or no issue key | `not-applicable`, silent |

`not-applicable` emits nothing at all, so generic GitHub behavior for
non-Agent-OS work is unchanged.

## Configuration

- `AGENT_OS_CHECKPOINT_STORE_ROOT` — existing #1218 descriptor-store root,
  supplied by host composition. There is no default: unset means unavailable,
  never a path to invent.
- `AGENT_OS_EXECUTION_INTERFACE_REPOSITORY` — optional `owner/name` override.
  Otherwise the identity is read from `.git/config`'s `origin` URL as a file;
  the adapter runs no subprocess and makes no network call.

Recognition of a governed checkout is repository evidence only
(`GOVERNED_CHECKOUT_MARKERS`). Chat text, branch names, labels, and issue prose
never make a checkout governed, and an extracted `#<n>` is a lookup key for the
existing locator, never authorization or command input.

## Boundary

The #1237 preflight is a locator consumer. The #1330 adapter is a #918 route
consumer. Neither introduces a second router, locator, descriptor store, index,
queue, transport, Scheduler, lease, retry system, GitHub writer, validation
authority, or execution authority. Neither synthesizes, ranks, or persists a
handoff, acquires a lease, invokes the Scheduler, runs Cloud Build, or performs a
repository mutation.

The repository contract cannot manufacture ChatGPT product/plugin behavior. A
host execution interface must consume the #918 decision and this bounded action
at its own tool-selection seam. Product/plugin changes remain outside this
repository implementation.

The `PreToolUse` guard is advisory only: it never denies, rewrites, or
pre-approves a tool call, and it emits no `permissionDecision`.

## Direct governed-resume invocation

```bash
scripts/agent-os-execution-interface-preflight.py \
  --repository Blummer92/agent-os --issue 1259 --store-root <path>
```

Prints canonical preflight JSON on stdout and the notice on stderr. The
entrypoint always exits `0`; fail-closed behavior is carried by the emitted
status, never by killing the host turn.

Tests: `tests/agent_os_execution_interface/`.

## Rollback

For #1330, remove
`scripts/agent_os_execution_interface/connector_native_fast_track.py` and its
focused regression test, then restore this note. #1237's existing hook, locator,
descriptor store, handoff identities, reconstruction, Scheduler state,
transport, branches, and PRs remain untouched.
