# Agent OS Candidate-Packet Live-Input Adapter (#1155)

## Purpose

`scripts.agent_os_candidate_packet.prepare_candidate_packet(...)` (#1105) is
complete and pure/read-only, but its `issue_reader: IssueSourceReader` and
`repository_reader: RepositoryEvidenceReader` parameters had no production
implementation anywhere in the repository -- only test doubles and the CLI's
fixture shims. This package supplies the smallest truthful, read-only bridge
so a caller can invoke the unchanged `prepare_candidate_packet(...)`
entrypoint against real GitHub/repository evidence instead of a
hand-authored fixture. It is a sibling of
`scripts/agent_os_candidate_packet` (deliberately network/subprocess-free)
and does not modify that package's public models, compiler, or CLI.

## Contents

- `issue_reader.py` -- `LiveIssueReader`, a production `IssueSourceReader`
  parameterized over an injected `SingleIssueTransport`.
- `repository_reader.py` -- `LiveRepositoryEvidenceReader`, a production
  `RepositoryEvidenceReader` that is truthfully always `UNAVAILABLE`.
- `repository_observation.py` -- a pure parser/assembler that builds a
  canonical `RepositoryObservation` from `scripts/verify-repo-state.sh`
  stdout plus explicit caller-supplied facts.

## Evidence observed automatically

- `LiveIssueReader`: nothing is inferred -- it normalizes exactly what the
  injected transport reports for one issue into the existing
  `IssueReadResult` / `IssueReadStatus` vocabulary.
- `repository_observation.py`: `head_ref`, `head_sha`, `base_ref`, `base_sha`,
  and `observed_sha` (set equal to `head_sha`) are parsed from
  `verify-repo-state.sh` stdout. `worktree_state` is `WorktreeState.CLEAN`
  only because a successful verifier run already proves a clean tracked
  tree (exit `3` otherwise, before any evidence is printed).

## Fields that remain caller-supplied

Every other `RepositoryObservation` field is an explicit, required keyword
argument with no default, matching `RepositoryObservation` itself:
`producer_adapter`, `producer_adapter_version`, `correlation_id`,
`repository_identity`, `contract_fingerprint`, `observed_at`,
`freshness_boundary`, `evidence_type`, and every optional SHA/ref the
verifier does not observe -- `requested_ref`, `requested_sha`, `tested_sha`,
`pushed_sha`, `proposed_pr_sha`, `synthetic_merge_sha`,
`external_build_sha`. A caller that omits one gets a `TypeError`, never a
silently invented value.

## Prohibited from inference

- `evidence_type` is never derived from the SHAs observed; the caller
  selects it explicitly.
- `worktree_state` is never set to anything but `CLEAN` by this assembler --
  a dirty tree means `verify-repo-state.sh` already failed upstream and
  produced no stdout to parse.
- Dependency/validation readiness is never guessed `RESOLVED_CLEAR`, and is
  never inferred from issue prose, labels, passing CI, branch state, or
  repository files.
- No approval, human-decision, or candidate-context field is touched by this
  package at all (`ApprovalCandidateContext`/`ApprovalDecision` remain
  separate human inputs owned by `scripts/agent_os_candidate_packet`).

## Why dependency/validation evidence is UNAVAILABLE

No structured live source for dependency or validation evidence exists
anywhere in this repository. `LiveRepositoryEvidenceReader` returns the
canonical `EvidenceStatus.UNAVAILABLE` with an explicit reason code
(`dependency.no-structured-source-configured` /
`validation.no-structured-source-configured`) rather than fabricating a
placeholder. Designing a real structured source is a separate future issue;
`UNAVAILABLE` is an acceptable truthful terminal answer here.

## Why `prepare_candidate_packet(...)` stays unchanged

This package only supplies alternate implementations of the two existing
`IssueSourceReader` / `RepositoryEvidenceReader` Protocols plus a
`RepositoryObservation` value, all consumed through the entrypoint's existing
parameters. No signature, schema, model, or compiler change was made in
`scripts/agent_os_candidate_packet`.

## Authority boundary

Read/prepare only. `LiveIssueReader` and `LiveRepositoryEvidenceReader` each
carry `execution_authorized: Literal[False]`. Neither this package nor the
entrypoint it feeds performs command execution (beyond the caller-run
`verify-repo-state.sh`, whose output is only parsed here), Scheduler/pilot
execution, provider calls, Git/worktree/lease execution, workflow changes,
protected-setting changes, or any other external write. All GitHub access
goes through the caller-supplied `SingleIssueTransport`; this package never
constructs a client, credential, or network connection itself.

## Rollback

Additive and self-contained: deleting
`scripts/agent_os_candidate_packet_live_input/` and
`tests/agent_os_candidate_packet_live_input/` fully reverts it. No other
package imports from it, and `scripts/agent_os_candidate_packet` is
unmodified.
