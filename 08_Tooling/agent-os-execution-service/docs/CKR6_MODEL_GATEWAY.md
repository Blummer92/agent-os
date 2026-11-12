# CKR6 model gateway (T13)

Mandatory CKR6 admission at an **application-owned model-execution boundary**.
This is local runtime code plus tests. It is **not installed anywhere**, holds no
credential, and grants no execution, GitHub-write, merge, or closure authority.
Native ChatGPT host enforcement (#2425, #3559) is a different surface and is
**not** claimed here.

## Decision (one narrow comparison)

| Option | Enforces | Fatal gap |
|---|---|---|
| A. Gate the worker launch | A session start | The launched CLI makes its own provider requests unseen |
| B. SDK adapter wrapper | Calls routed through it | T12's counterexample: any retained provider reference bypasses it |
| **C. Gateway that exclusively holds the provider capability (chosen)** | Every provider call | Needs OS isolation of workers; documented below |

A is applied only to the existing Claude launch seam and labelled
`session-start-only`. The generic POSIX launcher is not modified.

## Trust boundary

* **Trusted:** the process running `ModelGateway`. It alone holds the provider
  backend/credential and mints admission receipts. Receipts never leave it.
* **Untrusted:** workers. A worker is a separate OS process started by
  `supervisor.spawn_isolated_worker`: a **host-unique** unprivileged uid per
  worker, an empty network namespace verified to hold only `lo`,
  `no_new_privs`, its own session, a scrubbed environment, only the gateway
  socket inherited, and proof that root cannot be regained before `exec`. The
  worker starts only after the launcher reports readiness. Uid uniqueness is what
  stops one worker reading, ptracing, or `pidfd_getfd`-ing another's admitted
  gateway socket (QA reproduced that bypass with shared uids, then with
  colliding allocators). `UidAllocator` keeps a flock'd counter in a 0700,
  symlink-free state dir (default `/run/agent-os-ckr6-uid-alloc`, created only when a
  worker is first spawned) so supervisors and forks sharing it never draw the same
  uid. Exclusivity while a worker lives does **not** depend on that dir: `claim_uid`
  binds an abstract `AF_UNIX` name keyed by the uid, held from allocation through
  launch (a worker still in the root launcher phase is invisible to `/proc`), so
  supervisors with different state dirs or overlapping ranges cannot put two live
  workers on one uid either. A `/proc` scan (a worker orphaned by a crashed
  supervisor) and a real-account check back it up. Assumption: supervisors share
  one network namespace and uid space. `InProcessUidAllocator` is tests-only. It can send a **prompt** over
  `rpc.GatewayRpcServer`; frames cannot carry identity, materiality, admission,
  or receipts (strict per-method field allow-list). Repository, issue, task,
  attempt, and hints are fixed by the trusted side when the connection is made.
* **Fail closed:** if the host cannot isolate (not root, no `unshare`), the
  supervisor raises `IsolationUnavailable` and **no worker starts**.

## Admission (per request; no model, no caller assertion)

1. Materiality from the canonical `classify_envelope` (callers have no
   `specialized_knowledge_required` field). Failed-PR repair is always material
   under the canonical planner, so a `not-material` repair result is a downgrade.
2. Post the request once (never retried); **independent GET** and exact
   body/author/location/edit comparison.
3. Bounded poll (12 x 30 s, absolute 360 s) through the existing
   `select_ckr6_result_comment`; forged/edited/foreign results are discarded.
4. Independent reread; a changed or vanished result stops. Stricter than R07:
   `updated_at` is mandatory on request and result, the result must not be
   dated after the deadline or beyond 120 s ahead of the local clock, and the
   request's GitHub time must be within 120 s of the local clock.
5. Existing `ckr6_result_admits_boundary`, then gateway coherence checks
   (binding, five authority flags false, status vs materiality, selection).
6. Immediately before dispatch: the failed-attempt hook (mandatory for repair)
   and the optional `verify_binding_current` hook re-run (stale -> STOP). The
   issue-start head check exists only if the host supplies that hook.
7. One-time, expiring (60 s), prompt-bound, scope-bound receipt; consumed once.
   Receipts are defence in depth **inside** the trusted process (issued and
   consumed in one stack frame); the enforced property is the process and
   credential split, not receipt secrecy.

`unavailable-safe-fallback` admits only with an injected independent verifier
(default deny). A failed ingress is never converted into a fallback.

## Model-entry coverage

| Entry | Behavior |
|---|---|
| `invoke` (normal, retry, resume, tool-continuation, subagent) | Fresh full admission each; id is an idempotency key |
| `invoke_stream` / `session_stream` | Admission before first provider byte; no retry after partial stream; session closes |
| `open_session` + `session_turn` | One admission, bounded turns/expiry, **one receipt per provider call** |
| `session_child` (subagent) | Inherits binding/expiry; budget comes out of the parent; dies with it; depth bounded |
| retry / resume inside a session | Refused: needs a new admission |
| Claude launch (`gated_claude_launch`) | **Session-start only**; launch receipt cannot buy a provider call |

## What this does NOT enforce

* Real Claude CLI / SDK internal requests (no supported proxy path; not run).
* Anything on a host that cannot isolate workers; root or host-admin adversaries;
  a worker sharing the gateway's uid/netns; kernel escapes. No seccomp, cgroup,
  or filesystem namespace is applied.
* Python attribute privacy in the gateway process (`_backend`) is not a boundary.
  Never hand a `ModelGateway` to untrusted code: a direct caller chooses its own
  task text, hints, and prompt, and the prompt is not bound to the planner's
  materiality decision. Over RPC the binding is fixed by the trusted side.
* Filesystem `AF_UNIX` sockets a worker's uid may open (a provider or credential
  proxy must never be exposed that way), `AF_VSOCK`/`AF_NETLINK` creation, and
  PID/mount visibility: only the network namespace and uid are isolated.
* Selector semantics (Q1 R-01: id/payload coherence beyond the defensive check
  here) and failed-attempt record custody (PR #3772) are unchanged and owned elsewhere.
* No real transport (GitHub I/O) is shipped; `GitHubTransport` is a protocol.
  `fake_provider.py` is a fixture only.

## Tests

`tests/test_ckr6_model_gateway.py` drives the real R07 owners with a mutable
in-memory GitHub store (independent GET, delayed bot producer) and a fake
provider **running as a separate process** that counts authenticated calls and
refused attempts independently of the gateway. Isolation tests do not skip (CI
skip-veto): on a host that cannot isolate, `spawn_isolated_worker` raises and the
tests only assert that nothing started. **Such a run is NOT evidence of
isolation**; isolation evidence exists only for runs where
`isolation_available()` is true (root with `unshare`), which the evidence
package records. Findings and fixes from the independent QA pass are covered by
the `test_A1` / `test_B*` / `test_C*` regression tests.
