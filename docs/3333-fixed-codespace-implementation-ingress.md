# #3333 — Fixed Codespaces implementation ingress (non-authorizing phase)

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
