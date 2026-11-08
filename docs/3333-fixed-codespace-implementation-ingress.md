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
before execution reports null timestamps. Base-SHA and currentness remain recorded
bindings, not claims that a remote checkout was independently observed. New supplied
runner evidence binds the request ID; legacy requests without it retain their
existing content-derived identities.

Working-directory contract (#3333 Option B, owner-approved): the fixed-probe
Codespaces path no longer depends on the incidental non-interactive SSH working
directory. The transport honors a validated working directory, and the only
admissible value is the repository root `/workspaces/agent-os`; any other value
is rejected before any Codespace is contacted, and the remote command is pinned
under `cd '/workspaces/agent-os' &&` (a missing directory fails closed there,
before the fixed command runs). Repository identity -- not merely the directory
path -- is asserted on the remote side before execution: `git rev-parse
--show-toplevel` (already-admitted grammar, no allowlist widening) must report
exactly the validated root, otherwise the `&&` chain fails closed before the
fixed argv runs. The fixed argv itself is unchanged.

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
are permitted. The working directory is contract-supplied (the validated
repository root), never caller-supplied. This is a non-mutating HEAD verification canary, not the
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

The receipt also keeps the `TransportResult` evidence it previously dropped
(#3333 qualification Gate 5, repair R-1): `argv`, `stdout_truncated`,
`stderr_truncated`, `started_at`, `ended_at` and `duration_ms`. Before
dispatch `argv` is the fixed operation argv, both truncation flags are
`false`, and the three timing fields are `null`, so a refusal never claims
execution timing. After dispatch every field is copied from the transport
result. A result whose `argv` is not exactly `("git", "rev-parse", "HEAD")`
cannot complete. The additions are additive and keep `schema_version` `1.0`.
Host identity, lease disposition, QA correlation, an execution nonce and the
return path are not part of this repair; they keep their Gate 2/4/5 owners.

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

## Trusted-host provider connection (2026-10-14)

The #1287 composition now exposes the admission providers it already built:
`build_production_admission_providers(...)` returns `ProductionAdmissionProviders`.
The bundle holds the descriptor loader, the `CanonicalCurrentInvocationResolver`,
the `HostLocalLeaseAdapter` and the host clock (`evaluated_at`).
`build_production_governed_resume_bindings(...)` reconstructs with this same
bundle, so governed resume and the fixed probe cannot bind different stores,
leases or clocks.

`ProductionHostBootstrap.admission_providers()` returns that bundle for one host
process. It uses the same `AGENT_OS_CHECKPOINT_STORE_ROOT` check, sources and
lease directory as `governed_resume_bindings(...)`. It has no dispatch closure,
so the Scheduler cannot be reached from it.

A trusted host invokes the fixed probe like this:

```text
bootstrap = build_production_host_bootstrap(...)   # host state only
consume_fixed_codespace_pilot_on_host(
    transport,                                     # accepted #3333 envelope
    providers=bootstrap.admission_providers(),
)
```

`consume_fixed_codespace_pilot_on_host` checks the envelope first. It then
requires the exact `ProductionAdmissionProviders` type. Finally, it reads the
current Codespace through `read_canonical_codespace_selection`, which calls the
canonical shared `workflow_scheduler.governance.dev_validation_codespaces.resolve_current_codespace`.
The read lives in the execution service because `scripts/**` may not import
`workflow_scheduler` (the packaging guard in `tests/test_workflow_scheduler_packaging.py`).
A failed or non-canonical read blocks. The `resolve_selection` hook exists for
test fakes only. No issue-comment operand reaches it. Every admission, identity,
Codespace and receipt decision stays in `consume_fixed_codespace_pilot`.

Compatibility boundary: the probe still needs a *real* admitted #3333
`SingleIssuePilotInput`. That input exists only after the existing
`handoff_publication` producer has persisted a descriptor, checkpoint,
ResumePlan, authorization and lease identity for an actual pre-PR developer-loop
handoff. The HEAD probe is a read-only sub-operation of that admitted mission.
It never creates or substitutes that mission.

Unchanged: the Actions CLI `main()` has no host and still returns
`canonical-admission-provider-unavailable`. The operation stays
`codespace-implementation-pilot-v1` with argv `("git", "rev-parse", "HEAD")`.
No workflow, credential, host configuration, Codespace lifecycle, executor,
transport or store changed.

Regression coverage in `test_fixed_codespace_pilot.py` runs the real
`reconstruct_governed_invocation`, the currentness re-check, the dispatcher and
the transport. As in the #1218 suite, the cross-check results,
`SingleIssuePilotInput` and the lease request are patched, so stale and
authorization cases inject canonical reason codes. Only the missing-descriptor
case also runs over real providers and an empty store. Each case below must
fail closed:

- missing descriptor, including real providers over an empty store;
- stale checkpoint or ResumePlan, or invalid, replaced or expired authorization;
- conflicting, ambiguous or foreign lease;
- mismatched issue, handoff, source or remote SHA, or pilot tested SHA or repository;
- changed or unqualified Codespace selection, or a silent transport switch;
- missing environment-health evidence, unavailable runner, unsupported or empty capabilities;
- evidence that becomes unavailable after admission;
- malformed, non-zero, truncated or wrong-Codespace receipt, or an SSH timeout;
- an unauthorized operation or envelope.

None of this is live acceptance.

## Gate 2 bound evidence (R1, #3333)

The Gate 2 production controller previously built its production bootstrap
from an empty `LiveRepositoryEvidenceReader()`, which truthfully returned
UNAVAILABLE for every dependency/validation read, so no real candidate could
be reconstructed through that default path. The controller now uses the
existing governed-resume factory binding instead:
`build_production_host_bootstrap_for_handoff` loads the admitted handoff's
runtime request, descriptor, and restart capsule from the same checkpoint
store, verifies they bind the same subject, loads dependency readiness, and
rebuilds the advisory validation result into a bound reader, then supplies
that reader and runtime request to the existing production bootstrap.
The controller re-verifies the envelope's handoff, repository, issue, and
source SHA against the bound descriptor before any dispatch, shares the
controller's host configuration, lease directory, and evaluation clock with
the factory binding, and preserves the #3640 reason-code validation before
receipt persistence. Missing or inconsistent records fail closed as
`bound-evidence-unavailable` (a missing Gate 4 read credential keeps its
`github-read-credential-unavailable` reason); expired dependency readiness
is returned as UNAVAILABLE by the bound reader and therefore cannot be
admitted downstream. No new evidence model, controller, registry, scheduler,
or fallback was added, and no live host invocation, receipt return, or
Codespace qualification is claimed by this repair. The Actions CLI still
has no host and still returns `canonical-admission-provider-unavailable`.

## Codespaces runtime installation and host bindings (Gate 4)

`.devcontainer/post-create.sh` installs the existing `agent-os-execution-service`
distribution editable, once, after `requirements-dev.txt`. That order matters:
its `workflow-scheduler`, `agent-memory-context-manager` and
`instructional-workflow-contracts` requirements are local distributions that
`requirements-dev.txt` already supplies, and none is on a package index.
`requirements-dev.txt` does not list the execution service, so no second
bootstrap path installs it. A Codespace built from the profile can therefore
import `production_host_bootstrap` without a repository-root `PYTHONPATH`.

The trusted host reads four required absolute paths from its process
environment: `AGENT_OS_CHECKPOINT_STORE_ROOT`, `AGENT_OS_REPOSITORY_ROOT`,
`AGENT_OS_WORKSPACE_PARENT` and `AGENT_OS_LEASE_DIRECTORY`. The profile
deliberately **sets none of them**: `devcontainer.json` and `post-create.sh`
carry no value or placeholder. Choosing the real locations is a separately
authorized host-qualification step. Until then
`load_production_host_configuration` keeps refusing to run and names the first
missing variable. The loader also refuses blank values, and configuration
validation refuses relative paths.

This increment installs a package. It does not qualify the Codespace as a
trusted host, bind a host path, provision a credential, start or stop a
Codespace, or change the lease, lifecycle, transport, receipt or authorization
contracts. Gate 2 (lifecycle topology), the remaining Gate 4 identity and token
items, and Gate 5 R-2 (receipt return path) keep their owners.

## Admitted route operation (#3333 D3)

The probe is admitted only under a route whose `requested_operation` is
`pre-pr-developer-loop`, the operation every production publisher already binds
(`production_handoff_publication.PRE_PR_DEVELOPER_LOOP_OPERATION`). It previously
required `bounded-implementation`, which nothing outside tests produced, so no
real handoff could reach it. The retired `bounded-implementation` and the
lifecycle-only `validation-only` are both refused with
`canonical-identity-or-authorization-mismatch`.

Two identities stay separate. The route operation names the admitted mission. The
envelope operation `codespace-implementation-pilot-v1` and its reserved one-probe
authorization (comment 6176889694) are unchanged and still unconsumed. The fixed
argv is still `("git", "rev-parse", "HEAD")`, and the Actions entry still fails
closed with `canonical-admission-provider-unavailable`.

## Approved Codespaces checkpoint-store root (#3333)

The owner approved `/workspaces/agent-os-state/checkpoints` as the Codespaces
checkpoint-store root. `devcontainer.json` `containerEnv` binds
`AGENT_OS_CHECKPOINT_STORE_ROOT` to it for container processes, and
`post-create.sh` idempotently creates `invocations/` (mode 0700). sshd does not
pass `containerEnv`/`remoteEnv` to a noninteractive `gh codespace ssh -- <cmd>`
session, so the Codespaces discovery program also defaults to this root when the
variable is unset. The existing `handoff_publication` producer is authorized to
publish genuine pre-PR developer-loop descriptors there; a producer invoked over
SSH must use the same root. No descriptor is synthesized or copied from the
retired GCE host. This is not live acceptance.

## D1 workflow connection (2026-11-04)

The governed-invocation workflow now connects the fixed pilot to a
trusted host for the #3333 path only (Change Request v2.1 as corrected by
Addendum v2.2). No live pilot, descriptor publication, credential change,
repository-variable change, lifecycle operation, Ready, merge, or closure
is included; D2 remains a separate decision.

New steps in the `ingress` job, in order, all gated on the fixed
envelope. (The retired GCE `host_install` step no longer exists — #3821
removed it — so no D1 condition references it.)

1. **Preflight** (`fixed_preflight`): validates the four
   `vars.AGENT_OS_*` bindings (presence booleans only, never values),
   resolves the canonical Codespace selection, checks the runner main
   head against the comment SHA, checks the remote HEAD against the same
   SHA over the exact noninteractive SSH session, measures
   `CODESPACE_NAME` present-and-equal over that session, and runs the
   read-only Gate 2 `--check-bindings` probe. Any failure records a
   blocked `gate2-transfer.json` and `ready=false`; the step itself
   exits 0 so the acceptance gate below is the terminal boundary.
2. **Exclusive transfer** (`fixed_transfer`): stages the raw event
   outside the uploaded ingress directory, under
   `$RUNNER_TEMP/agent-os-gate2-private/` (0700 directory, 0600 file,
   umask 077, size bound 1,048,576 bytes), creates a fresh 0700 remote
   directory (exists means blocked, never overwritten), copies without
   `--expand`, guards regular-file/not-symlink, verifies the staging
   SHA-256, links atomically (`ln`, never copy-over), and verifies the
   final SHA-256 plus staging/final inode equality. Remote names are
   built only from validated numeric run/attempt values plus fixed
   literals; event text is never interpolated into any command.
3. **Run + receipt return** (`fixed_run`): invokes the existing Gate 2
   controller over SSH with quoted `AGENT_OS_*` assignments and the
   constructed `--event` path, captures stdout/stderr separately into
   `gate2-stdout.json` / `gate2-stderr.json`, and, only on exit 0,
   returns the receipt by staging plus atomic link after validating the
   full receipt-path prefix (store root + `/invocations/receipts/`).
   A non-zero Gate 2 exit records the stderr reason for the gate; the
   step itself exits 0. A 300 s timeout (exit 124) is different: the
   remote controller may have finished, or may still hold its O_EXCL
   claim, so the gate records `run-timeout-outcome-uncertain` — a
   fail-closed FAIL that asserts neither success nor failure. The claim
   and any host receipt are preserved, nothing is retried automatically,
   and the next run fails with `fixed-pilot-claim-ambiguous` until an
   owner adjudicates the uncertain outcome.

   **Change B — explicit host-local transport (D2).** The trusted Gate 2
   controller is already running inside the selected Codespace through the
   outer Actions SSH hop. For the production fixed pilot (without a test-
   injected dispatcher), the existing canonical dispatcher now requests
   `codespace-host-local` explicitly instead of opening a second SSH
   connection back to the same Codespace. The normal transport SSH mode
   remains available for other callers. Local mode requires the exact
   canonical repository root, a named and uniquely qualified Codespace,
   and equality with the host `CODESPACE_NAME`; it checks the repository
   root using a separate fixed `git rev-parse --show-toplevel` subprocess,
   then runs only the already allowlisted argv with a fixed system PATH,
   minimal child environment, closed stdin and process-group timeout kill.
   No fallback to SSH or GCE is allowed. Mode is bound into the request ID;
   old SSH request IDs are unchanged. The Gate 2 claim and receipt logic from
   Change A, the workflow, credential configuration and acceptance gate are
   unchanged. A clean, separately authorized live pilot remains required.

   **Change A — uncertain-outcome classification (D2).** Before this
   change, the pilot labelled a timeout, a transport error after start,
   a non-zero SSH client exit, and a post-dispatch exception with the
   same retryable reasons as refusals where provably nothing ran, and
   the controller released its claim after any verified persistence —
   so a second owner comment re-executed the fixed argv. Now the pilot
   reports those outcomes as `execution-outcome-uncertain` (with a
   `transport-timeout`, `transport-error`, or
   `post-dispatch-evidence-unavailable` detail), reports a transport
   result with no start time as `codespace-transport-not-started` with
   a `transport-*` detail and `side_effects_performed=false`, and the
   controller releases the claim only for a completed receipt or a
   receipt whose every reason code is in the
   `PRE_EXECUTION_REASON_CODES` allow-list. Any other or unknown reason
   retains the claim; the next run fails with
   `fixed-pilot-claim-ambiguous` until the owner verifies nothing is
   in flight, inspects the receipt, and removes the claim file by hand.
   Exit-0 known failures (for example a stale HEAD) also retain the
   claim, by the same fail-closed policy. The nested-SSH hop itself is
   unchanged.
4. **Acceptance gate** (`fixed_gate`, `if: always()`, no
   `continue-on-error`): runs `dev_validation_gate --fixed-pilot` over
   transport, diagnostic, reference, process stderr, receipt, transfer,
   and the private event file, writes `gate2-gate.json`, and exits 1
   unless the decision is PASS. It runs before the invocation summary.
5. **Cleanup** (`fixed_cleanup`, only on gate PASS): removes the remote
   staging directory and the runner private staging. On gate FAIL the
   remote directory is left in place for diagnosis. Cleanup never
   touches the host receipt, any claim, or any artifact file, and never
   fails the job; its outcome is recorded in `gate2-cleanup.json`.

**Acceptance validator** (`dev_validation_gate --fixed-pilot`): requires
the genuine 30-field completed receipt (the producer's 27-key template
plus `admission_id`, `invocation_id`, `descriptor_id`), the exact
10-field reference (`operation_id`, not `operation`), transport
identities (repository, issue 3333, actor, run attempt 1, handoff, SHA),
transfer evidence (preflight booleans, VALID probe, dual SHA-256,
inode equality, run exit 0, receipt returned), an empty Gate 2 stderr
channel, and a private event whose bytes and SHA-256 still match the
transfer record. Check order preserves the originating failure: a Gate 2
stderr reason is reported verbatim instead of being masked by the
missing reference or receipt it also explains. One exception precedes
stderr parsing: a 300 s timeout (transfer `run_rc` 124) short-circuits
to `run-timeout-outcome-uncertain`, because a killed controller's
stderr cannot say whether the remote run finished. A workflow exit 0, a
reference alone, or the provider-less diagnostic can never pass.

**Gate 2 `--check-bindings`** (the only Gate 2 change in D1): a
read-only probe verifying the four bound paths, the initialized store,
strict host identity, and an empty lease directory. It creates no state
(no receipts directory), reads no event, acquires no claim, and
dispatches nothing. The strict `CODESPACE_NAME` rule is unchanged:
absent means `host-surface-identity-unavailable`, different means
`host-surface-identity-mismatch`, and only present-and-equal passes.
The v2.1 absent-tolerance amendment was withdrawn in v2.2 and is not
implemented.

**Summary precedence**: for fixed envelopes the summary prints the
diagnostic status, the gate decision and reasons, and the line
"Provider-less diagnostic only; not execution evidence." The generic
`Dispatch: None / None` fallback is suppressed for fixed envelopes.
The seven-day artifact upload step is unchanged and still publishes the
whole ingress directory after acceptance and summary.

**D1/D2 source rule**: D2 requires this patch merged to main and the
selected host's checkout at the merged main commit exactly. A D2 attempt
from a PR head is not permitted, and no checkout is ever reset, cleaned,
or replaced to achieve a matching state.

**Publication honesty**: the #1411 chain still contains no assertion
that `projection.tested_repository_sha == packet.candidate_sha`, and no
chain line asserts the execution request's `expected_sha` equals the
candidate SHA. Both equalities remain P-descriptor/D2 blockers enforced
by publication readback plus Gate 2, not by D1 code. D1 adds no
publication authority and no hand-written descriptor.

**Rollback**: revert only the five new workflow steps, the summary
precedence hunk, the validator's fixed-pilot mode, the Gate 2
`--check-bindings` mode, and their tests/docs. The diagnostic, GCE,
Notion, Ready, merge, and developer-validation paths are untouched.
