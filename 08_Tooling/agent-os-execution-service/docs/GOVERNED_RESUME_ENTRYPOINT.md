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
#1304 (AOS-GCE2E) made the four artifacts `HostCurrentInvocationSources` still needs concrete readers for -- route decision, full handoff, checkpoint-by-id, `ResumePlan` -- durably persist/read-by-id; wiring those readers here remains #1303's scope.

## Production host bootstrap (#1319 / AOS-GCE2E)

`production_host_bootstrap.build_production_host_bootstrap(...)` is the one
repository-owned boundary that turns trusted host state into the #1303
`ProductionHostStateSources`, and
`ProductionHostBootstrap.governed_resume_bindings(...)` hands those seven source
methods to the #1287 composition above. It composes only: no reconstruction,
authorization, Scheduler, lease, store, checkpoint, router, retry, or
transport-control-plane semantics live here.

### Host configuration

Static host locations come from the process environment only -- never from
argv, issue text, issue-comment text, or a handoff payload -- extending the
existing `AGENT_OS_CHECKPOINT_STORE_ROOT` convention rather than opening a
second configuration source of truth:

| Variable | Required | Meaning |
|---|---|---|
| `AGENT_OS_CHECKPOINT_STORE_ROOT` | yes | Checkpoint/descriptor/capsule store root (the same variable `production_host_composition` binds). |
| `AGENT_OS_REPOSITORY_ROOT` | yes | Absolute path of the governed checkout the canonical verifier runs in. |
| `AGENT_OS_WORKSPACE_PARENT` | yes | Absolute parent directory for Scheduler workspaces. |
| `AGENT_OS_LEASE_DIRECTORY` | yes | The one host-local Scheduler lease directory. |
| `AGENT_OS_DELEGATED_PARENT_CGROUP` | no | The already-qualified delegated cgroup the #1238 wrapper establishes. |
| `AGENT_OS_REPOSITORY_HOST` | no | Git host for the repository identity. Defaults to `github.com`. |

Every required path must be absolute, and a missing or blank value fails closed
naming the variable. `governed_resume_bindings(...)` re-checks that the bound
store root still matches `AGENT_OS_CHECKPOINT_STORE_ROOT` so two store
locations can never be composed. The one configured `lease_directory` reaches
both the #1303 sources (which bind it into the runtime configuration) and the
#1287 composition (which observes and dispatches against it), so
reconstruction-time and dispatch-time lease directories cannot diverge.

`evaluated_at` comes from `canonical_evaluated_at()` -- the host clock at
bootstrap, in canonical UTC seconds -- never from caller-controlled input. A
naive datetime fails closed instead of being assumed to be UTC.

### Read transports

`host_github_read_transport.HostGitHubReadTransport` is the smallest reusable
adapter over the GitHub access boundary this repository already has. Current
`main` has canonical read-only PyGithub transports
(`scripts/agent_os_github_issue_provider`, `scripts/agent_os_github_git_objects`)
but neither exposes a single-issue read or an issue-comments read, so one
object over one injected JSON read callable satisfies **both** contracts rather
than two independent clients:

- `get_issue(...)` satisfies `SingleIssueTransport`; `LiveIssueReader` (#1155)
  stays the sole owner of issue normalization and fail-closed status mapping.
- `read_authorization_source(...)` satisfies
  `ExecutionAuthorizationSourceTransport`; `reacquire_execution_authorization(...)`
  stays the sole owner of trust, currentness, binding, and revocation. A
  comment page budget that cannot cover the snapshot's own bound reports
  `comments_complete=False`, which that owner already maps to
  `source-incomplete` / `needs-decision`.

`build_host_github_read_transport_from_environment(...)` reuses the existing
`GITHUB_TOKEN`/`GH_TOKEN` convention (`scripts/agent_os_github_git_objects/cli.py`)
and the existing PyGithub auth boundary. No new credential, IAM, GitHub App, or
network control plane is introduced, and the token is never stored on, logged
by, or echoed from any object here. Both new modules import `github` and
`subprocess` locally, so offline tests import them with no process, network, or
credential machinery.

### Repository observation

`build_repository_observation_reader(...)` runs the canonical
`scripts/verify-repo-state.sh` with a fixed argv (`shell=False`, no
caller-supplied command, no caller-supplied root) under the configured
repository root, and assembles the result through the canonical
`build_repository_observation_from_verifier_stdout(...)`. Git state is never
reimplemented: the script is the only thing that runs Git, and only its
documented exit code enters diagnostics -- its stderr never becomes governed
evidence. The branch pair comes from the trusted restart capsule (#1303
consumes `observation.base_sha` as `evaluated_repository_sha`, so the verifier
is asked for the base branch the candidate packet is pinned to), and every
field the assembler leaves to the caller is bound from an existing canonical
owner: `correlation_id` from the descriptor's `invocation_id`,
`contract_fingerprint` from the approval record's
`implementation_contract_fingerprint`, `freshness_boundary` from the candidate
packet, `requested_ref`/`requested_sha` from the pinned base branch and base
SHA (so live base drift fails closed), and `tested_sha`/`pushed_sha`/
`proposed_pr_sha`/`synthetic_merge_sha` as explicit `None` because the verifier
does not observe them.

### AOS-GCE2F dependency

`required_environment_spec_reader` is #1320's
`build_required_environment_spec_reader(store_root)`, composed without learning
its source-of-truth internals. `repository_evidence_reader` is a **required**
argument and is #1320's `LiveRepositoryEvidenceReader` (or another canonical
`RepositoryEvidenceReader`): this bootstrap supplies no default and no
substitute, because inventing an evidence source would be exactly the second
source of truth #1319 forbids. An absent binding fails closed before any
Scheduler dispatch is reachable.

### Known cross-contract gap

`verify-repo-state.sh` prints `BASE_REF=origin/<base>` while the repository
stage compares `base_ref` against the planning handoff's plain `<base>`. That
vocabulary difference is latent in current `main` -- it predates this bootstrap,
in the canonical assembler and the verifier contract -- and is owned by those
contracts, not by this composition boundary. Until it is reconciled, a live
governed resume reaches the repository stage and fails closed there rather than
admitting; offline composition, binding, and fail-closed behaviour are
unaffected. Live qualification remains #1239.

### Rollback for this slice

Revert `production_host_bootstrap.py`, `host_github_read_transport.py`, their
focused tests, this section, the `scripts.agent_os_candidate_packet_live_input`
packaging entry, and the CHANGELOG record. Leave #1303, #1287, #1320, #1300,
#1238, #1218/#1253, Scheduler leases, checkpoint evidence, and external
resources unchanged.
