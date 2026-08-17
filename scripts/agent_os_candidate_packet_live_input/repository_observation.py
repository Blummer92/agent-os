"""Pure ``verify-repo-state.sh`` stdout parser/assembler for ``RepositoryObservation``.

Reads the documented stdout evidence contract
(``scripts/verify-repo-state-contract.md``) rather than reimplementing Git
logic: ``scripts/verify-repo-state.sh`` itself is the only thing that ever
runs Git. This module performs no clone, checkout, command execution,
credential access, or network call of any kind -- it only parses a string the
caller already captured from a successful verifier run.

Automatically derived from verifier stdout: ``head_ref``, ``head_sha``,
``base_ref``, ``base_sha``, and ``observed_sha`` (the SHA the verifier proved
was actually checked out at ``HEAD``). ``worktree_state`` is set to
``WorktreeState.CLEAN`` only because a successful verifier run already
guarantees a clean tracked tree (the script exits 3 on uncommitted tracked
changes before ever printing evidence) -- never inferred beyond what the
script proved.

Every other ``RepositoryObservation`` field --
``producer_adapter``/``producer_adapter_version``/``correlation_id``/
``repository_identity``/``contract_fingerprint``/``observed_at``/
``freshness_boundary``/``evidence_type`` plus every optional SHA the verifier
does not observe (``requested_ref``, ``requested_sha``, ``tested_sha``,
``pushed_sha``, ``proposed_pr_sha``, ``synthetic_merge_sha``,
``external_build_sha``) -- remains an explicit, required caller-supplied
argument with no default, matching ``RepositoryObservation`` itself. A caller
that omits one gets a ``TypeError``, never a silently invented value.

Malformed, incomplete, duplicate, or ambiguous verifier stdout fails closed
with ``VerifierStdoutError`` rather than being repaired or partially
accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
    WorktreeState,
)

_REQUIRED_KEYS = ("HEAD_REF", "HEAD_SHA", "BASE_REF", "BASE_SHA")
_CHANGED_FILES_BEGIN = "CHANGED_FILES_BEGIN"
_CHANGED_FILES_END = "CHANGED_FILES_END"
_HEX_DIGITS = frozenset("0123456789abcdef")
_SHA_LENGTH = 40


class VerifierStdoutError(ValueError):
    """Raised when ``verify-repo-state.sh`` stdout does not match its contract."""


@dataclass(frozen=True, slots=True)
class VerifierEvidence:
    """The four fields ``verify-repo-state.sh`` stdout truthfully supplies."""

    head_ref: str
    head_sha: str
    base_ref: str
    base_sha: str


def parse_verifier_stdout(stdout: str) -> VerifierEvidence:
    """Parse one successful ``verify-repo-state.sh`` stdout capture.

    Requires exactly the four documented ``KEY=VALUE`` lines, each present
    once, followed by a ``CHANGED_FILES_BEGIN``/``CHANGED_FILES_END`` block
    (its contents are not needed by this assembler and are not returned).
    Anything else -- missing keys, duplicate keys, unknown keys, a missing
    marker, or a malformed ref/SHA -- fails closed with
    ``VerifierStdoutError``.
    """
    if not isinstance(stdout, str):
        raise TypeError("stdout must be a string")

    lines = stdout.splitlines()
    values: dict[str, str] = {}
    begin_index: int | None = None
    for index, line in enumerate(lines):
        if line == _CHANGED_FILES_BEGIN:
            begin_index = index
            break
        if not line:
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise VerifierStdoutError(f"malformed verifier stdout line: {line!r}")
        if key not in _REQUIRED_KEYS:
            raise VerifierStdoutError(f"unexpected verifier stdout key: {key!r}")
        if key in values:
            raise VerifierStdoutError(f"duplicate verifier stdout key: {key!r}")
        values[key] = value

    if begin_index is None:
        raise VerifierStdoutError(
            f"verifier stdout is missing the {_CHANGED_FILES_BEGIN} marker"
        )
    if _CHANGED_FILES_END not in lines[begin_index + 1 :]:
        raise VerifierStdoutError(
            f"verifier stdout is missing the {_CHANGED_FILES_END} marker"
        )

    missing = [key for key in _REQUIRED_KEYS if key not in values]
    if missing:
        raise VerifierStdoutError(
            "verifier stdout is missing field(s): " + ", ".join(missing)
        )

    return VerifierEvidence(
        head_ref=_validate_ref(values["HEAD_REF"], "HEAD_REF"),
        head_sha=_validate_sha(values["HEAD_SHA"], "HEAD_SHA"),
        base_ref=_validate_ref(values["BASE_REF"], "BASE_REF"),
        base_sha=_validate_sha(values["BASE_SHA"], "BASE_SHA"),
    )


def build_repository_observation_from_verifier_stdout(
    verifier_stdout: str,
    *,
    producer_adapter: str,
    producer_adapter_version: str,
    correlation_id: str,
    repository_identity: RepositoryIdentity,
    contract_fingerprint: str,
    observed_at: str,
    freshness_boundary: str,
    evidence_type: RepositoryEvidenceType,
    requested_ref: str | None,
    requested_sha: str | None,
    tested_sha: str | None,
    pushed_sha: str | None,
    proposed_pr_sha: str | None,
    synthetic_merge_sha: str | None,
    external_build_sha: str | None,
    worktree_reason_codes: tuple[str, ...] = (),
) -> RepositoryObservation:
    """Assemble one ``RepositoryObservation`` from verifier stdout plus caller facts.

    ``head_ref``/``head_sha``/``base_ref``/``base_sha``/``observed_sha`` come
    from the parsed verifier stdout (``observed_sha`` is the same
    ``head_sha`` the verifier proved was actually checked out).
    ``worktree_state`` is always ``CLEAN``: a verifier run that did not prove
    a clean tracked tree never reaches stdout at all (it exits 3 first), so
    this function has nothing else to set it from. Every other argument is
    the caller's own explicit fact and is passed through to
    ``RepositoryObservation`` unchanged -- this function derives no
    ``evidence_type``, no optional SHA, and no identity of its own.
    """
    evidence = parse_verifier_stdout(verifier_stdout)
    return RepositoryObservation(
        producer_adapter=producer_adapter,
        producer_adapter_version=producer_adapter_version,
        correlation_id=correlation_id,
        repository_identity=repository_identity,
        base_ref=evidence.base_ref,
        base_sha=evidence.base_sha,
        head_ref=evidence.head_ref,
        head_sha=evidence.head_sha,
        requested_ref=requested_ref,
        requested_sha=requested_sha,
        observed_sha=evidence.head_sha,
        tested_sha=tested_sha,
        pushed_sha=pushed_sha,
        proposed_pr_sha=proposed_pr_sha,
        synthetic_merge_sha=synthetic_merge_sha,
        external_build_sha=external_build_sha,
        evidence_type=evidence_type,
        contract_fingerprint=contract_fingerprint,
        worktree_state=WorktreeState.CLEAN,
        observed_at=observed_at,
        freshness_boundary=freshness_boundary,
        worktree_reason_codes=worktree_reason_codes,
    )


def _validate_ref(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or normalized != value:
        raise VerifierStdoutError(f"{field_name} is malformed: {value!r}")
    return normalized


def _validate_sha(value: str, field_name: str) -> str:
    if len(value) != _SHA_LENGTH or not _HEX_DIGITS.issuperset(value):
        raise VerifierStdoutError(f"{field_name} is malformed: {value!r}")
    return value
