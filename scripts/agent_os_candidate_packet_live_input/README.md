# Agent OS Candidate-Packet Live-Input Adapter (#1155, #1320)

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
  `RepositoryEvidenceReader` that maps canonical structured evidence into the
  existing `DependencyEvidence`/`ValidationEvidence` vocabulary, and stays
  truthfully `UNAVAILABLE` when no structured evidence is supplied.
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
  repository files. It comes only from the canonical structured owners
  described under "Structured dependency/validation evidence (#1320)" below.
- No approval, human-decision, or candidate-context field is touched by this
  package at all (`ApprovalCandidateContext`/`ApprovalDecision` remain
  separate human inputs owned by `scripts/agent_os_candidate_packet`).

## Structured dependency/validation evidence (#1320)

AOS-GCE2F (#1320) gave this adapter its first structured sources. It owns no
evidence of its own: it re-reads two existing canonical owners and translates
them into the two existing evidence vocabularies.

| Output | Canonical source of truth | Owner |
| --- | --- | --- |
| `DependencyEvidence` | `DependencyReadinessEvidence` | #1185/#1197 runtime dependency readiness |
| `ValidationEvidence` | `AdvisoryEvidenceResult` | existing `scripts.agent_os_remote_validation` pre-PR advisory evidence |
| identity the readiness must match | `RequiredEnvironmentSpec` | `scripts.agent_os_execution_capabilities.dependencies` |

Construct the reader with no arguments and the original #1155 behaviour is
unchanged: both reads are `EvidenceStatus.UNAVAILABLE` with
`dependency.no-structured-source-configured` /
`validation.no-structured-source-configured`. Supplying structured evidence also
requires the subject it belongs to (`repository`, `issue_number`), so evidence
for another repository, issue, plan, or required environment can never be read
as this subject's.

### Mapping

`DependencyReadinessEvidence.preparation_status` `ready` becomes
`RESOLVED_CLEAR`; `preparation-required`, `source-update-required`, `blocked`,
and `failed` become `RESOLVED_BLOCKED` carrying the evidence's own reason codes.
Advisory `passed` becomes `RESOLVED_CLEAR`; `failed`/`incomplete` become
`RESOLVED_BLOCKED`; `needs-decision` becomes `NEEDS_DECISION`; `stale`/`invalid`
and any unrecognized status become `UNAVAILABLE`.

### Fail-closed conditions

Every one of these yields `UNAVAILABLE` with an explicit reason code, never a
guess: no structured evidence supplied; evidence bound to a different
repository, issue, or validation plan; readiness whose `required_environment_id`,
ecosystem, package root, or install mode does not match the current
`RequiredEnvironmentSpec`; readiness that is not current at the evaluation
moment; a malformed evaluation moment; an unrecognized advisory status.

### Declarative requirements are not runtime readiness

A `RequiredEnvironmentSpec` is declarative requirement data. Supplying one
without current `DependencyReadinessEvidence` stays `UNAVAILABLE` -- the spec
alone never produces `RESOLVED_CLEAR`. Restart-capsule or descriptor presence is
likewise binding context only and never evidence of readiness.

### Still prohibited from inference

GitHub check runs, generic CI status, PR state, issue labels, issue prose,
branch names, timestamps, and repository-file accidents are never consulted for
either evidence. This adapter introduces no second dependency-readiness model,
validation selector, evidence store, Scheduler, retry authority, or execution
authority.

## Why `prepare_candidate_packet(...)` stays unchanged

This package only supplies alternate implementations of the two existing
`IssueSourceReader` / `RepositoryEvidenceReader` Protocols plus a
`RepositoryObservation` value, all consumed through the entrypoint's existing
parameters. No signature, schema, model, or compiler change was made in
`scripts/agent_os_candidate_packet`.

## Authority boundary

Read/prepare only. `LiveIssueReader` and `LiveRepositoryEvidenceReader` each
carry a `False` `execution_authorized` field. Neither this package nor the
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
