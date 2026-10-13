# #3333 — Fixed Codespaces implementation ingress (non-authorizing phase)

## Bounded transport repair (2026-10-12)

The existing transport now admits a finite grammar rather than trusting every
executable except `git push`/`gh`/`hub`. Commands are limited to:

- Git status/diff/show/log/rev-parse/ls-files, plus worktree list and bounded
  worktree add (detach or a non-main local branch);
- ripgrep repository search/file listing without executable preprocessors;
- pytest, directly or `python[3] -m pytest`, with bounded test paths/options.

Unknown executables, executable paths, shells/wrappers, inline Python, arbitrary
scripts/modules, Git global configuration/aliases, executable diff helpers,
pytest plugin/config overrides, and GitHub clients are refused before Codespace
discovery. Argv has token/count/total-size bounds and excludes control characters.
The policy is part of this same transport; it defines no executor route, command
ingress, authorization model, agent, Scheduler or persistence mechanism.

SSH interprets remote commands through the remote shell. The transport quotes
each admitted argument for that boundary; it does not accept caller shell text.
Local subprocess execution remains argv-based. Pattern/path text stays data.

Result evidence includes fixed repository/execution surface, canonical runner
profile/health references when supplied, UTC local transport-attempt start/end,
and monotonic duration. Timeout/error results retain attempt timestamps; refusal
before execution reports null timestamps. Caller-owned workdir/base/currentness
remain recorded bindings, not claims that a remote checkout or working directory
was independently observed. New supplied runner evidence binds the request ID;
legacy requests without it retain their existing content-derived identities.

These operations require a qualified environment and trusted admitted repository
and test code. The argv grammar does not sandbox arbitrary repository code or
grant GitHub/publication/merge authority. Workflow/credential/lifecycle changes
remain separately gated, and this repair does not expose multi-file editing or
replace WSC5/CodingWorker's caller-owned implementation plan.

Focused regressions: `test_codespace_transport_contract.py` is stdlib unittest
compatible and also collected by the existing pytest CI. The existing transport,
dispatcher and fixed-probe pytest suites remain exact-head validation obligations.
The fixed `git rev-parse HEAD` canary below is still the only production payload;
the live general engineering pilot is separate acceptance.

This is a bounded integration increment for #3333. It is **not** proof of
live ChatGPT-to-Codespaces acceptance, and it does not expose a generic shell.

## Fixed low-trust envelope

```text
/agent-os codespace-implementation executor-handoff:<64 lowercase hex> <40 lowercase hex SHA>
```

Only owner-created comments on issue #3333, first workflow attempt, matching
repository and exact grammar, are accepted by the existing
`github_issue_comment_ingress`. Parsing does not authorize execution.

The fixed operation identity is `codespace-implementation-pilot-v1`.
The only transport argv in this increment is `("git", "rev-parse", "HEAD")`.
No caller-supplied command, workdir, host, token, arbitrary arguments or paths
are permitted. This is a non-mutating HEAD verification canary, not the
multi-file implementation pilot.

## Host admission and currentness

`scripts.agent_os_execution_interface.fixed_codespace_pilot` consumes
the canonical #1218 `reconstruct_governed_invocation` result. A qualified
host must provide the existing descriptor loader, current-evidence resolver,
lease observer and current Codespace selection; no issue-comment operand
selects these trusted providers.

An `ADMITTED` result alone is not a GitHub mutation authorization. The
consumer also reacquires descriptor/current bindings, checks exact issue,
handoff, SHA, current authorization, route, environment identity, and qualified
Codespace identity before invoking the existing #3333 dispatcher. The
transport then enforces its own forbidden-command and single-Codespace rules.
A remote HEAD mismatch is a blocked receipt, never a success.

**Current deployment boundary:** the existing Actions runner does not have
the canonical checkpoint/descriptor store and lease/current-evidence providers
for an ordinary ChatGPT implementation mission. Its CLI therefore returns
`canonical-admission-provider-unavailable` without dispatching. This
explicit refusal is intentional until a supported qualified host supplies
those existing providers. Never replace them with synthetic readiness flags
or a fabricated authorization ID.

## Actions isolation and receipts

The existing governed invocation workflow routes the new fixed operation to
this consumer and excludes it from unrelated Codespaces diagnostics,
developer-validation, discovery, and GCE fallback. The existing result JSON
artifact remains the bounded receipt location. No new scheduler, queue,
executor, MCP server, credential, permissions or publication mechanism is
introduced.

Receipt identity: operation, issue, handoff, expected SHA, logical trigger,
status/reasons, request ID (only after dispatch), Codespace name, bounded
output, exit status, and explicit false GitHub/publication/merge authority.
A blocked preflight must not claim a Codespaces execution receipt.

## Verification and next acceptance

Focused tests: `tests/agent_os_execution_interface/test_fixed_codespace_pilot.py`
plus existing ingress/transport tests. Exact-head CI on the Draft PR is
required before readiness. Live synchronous ChatGPT host invocation and a
multi-file implementation/test pilot remain **NOT RUN**, requiring separate
authorization and qualified host configuration. This increment cannot close
#3333 or satisfy its live Definition of Done.

## Rollback

Revert only the new fixed ingress, dedicated consumer, workflow gating, and
their tests/docs. Existing transport, developer-validation, diagnostic,
discovery, GCE control, publication and CI remain unchanged.

## Production host provider compatibility (#1287)

The existing `ProductionHostBootstrap.governed_resume_bindings(...)` composes
`build_production_governed_resume_bindings(...)`, which owns the descriptor
loader, `CanonicalCurrentInvocationResolver`, and `HostLocalLeaseAdapter`.
It requires host-controlled `AGENT_OS_CHECKPOINT_STORE_ROOT`, repository and
workspace roots, a lease directory, current GitHub authorization transport,
and live repository evidence readers. These dependencies are not provided by
the issue-comment Actions runner.

The existing composition reconstructs a Scheduler `SingleIssuePilotInput`;
it is not automatically the admission source for ordinary ChatGPT coding
missions. Before wiring production dispatch, verify that the actual admitted
mission is compatible with that model, including the exact issue, source SHA,
execution identity, and lease. Never create synthetic authorization records,
lease observations, or a second persistence store to make the adapter runnable.

The consumer now also rejects a partial host binding with
`canonical-host-binding-incomplete`. This is a repository-side safety check,
not a claim that the live host provider is connected.

