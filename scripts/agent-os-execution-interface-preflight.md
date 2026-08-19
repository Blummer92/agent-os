# Execution-interface governed-route preflight (#1237)

## Failure removed

```text
work on an Agent OS issue -> generic GitHub publish tooling selected first
-> local `gh` prerequisite checked -> `gh` absent -> false blocker
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

## Resolved path

```text
governed Agent OS checkout + resolved repository + exactly one issue key
-> existing #1237 read-only handoff discovery
-> exactly one valid descriptor
-> existing immutable executor-handoff:<sha256>
-> existing bounded `/agent-os resume <id>` ingress
-> existing GitHub -> WIF -> GCE transport, #1238 host entrypoint,
   #1218/#1253 reconstruction, existing Workflow Scheduler
```

## Outcomes

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

The preflight is a locator consumer. It introduces no second router, locator,
descriptor store, index, queue, transport, Scheduler, lease, retry system, or
execution authority; it never synthesizes, ranks, or persists a handoff, never
acquires a lease or invokes the Scheduler, and grants no implementation, cloud,
merge, issue-closure, or publication authority. A discovered identity must still
pass the existing #1218/#1253 reconstruction, authorization, source/scope,
checkpoint, ResumePlan, environment, and lease checks before any execution.

The `PreToolUse` guard is advisory only: it never denies, rewrites, or
pre-approves a tool call, and it emits no `permissionDecision`.

## Direct invocation

```bash
scripts/agent-os-execution-interface-preflight.py \
  --repository Blummer92/agent-os --issue 1259 --store-root <path>
```

Prints canonical preflight JSON on stdout and the notice on stderr. The
entrypoint always exits `0`; fail-closed behavior is carried by the emitted
status, never by killing the host turn.

Tests: `tests/agent_os_execution_interface/`.

## Rollback

Remove `.claude/settings.json`, `scripts/agent-os-execution-interface-preflight.py`,
`scripts/agent_os_execution_interface/`, `tests/agent_os_execution_interface/`,
and this note. The existing locator, descriptor store, handoff identities,
reconstruction, Scheduler state, transport, branches, and PRs are untouched.
