"""Gate 2 (#3333) production-host controller: the fixed HEAD pilot's trusted host process.

This module is the smallest runnable production-host entrypoint for the #3333
Codespaces live execution pilot. It owns no admission, authorization, lease,
transport, dispatch, or receipt semantics of its own: it is a thin fail-closed
ordering over already-shipped components:

- the canonical #1218 issue-comment ingress (``admit_issue_comment_event``)
  admits the owner's per-invocation comment into the accepted fixed-pilot
  envelope; no envelope is ever synthesized here and CURRENT execution
  authorization is never invented;
- ``load_production_host_configuration`` binds the four ``AGENT_OS_*`` paths,
  fail-closed on any missing binding;
- ``build_production_host_bootstrap_for_handoff`` (the existing
  governed-resume factory, #1217/#1319) supplies the one read-only host
  transport, the handoff-bound runtime request, and a
  ``LiveRepositoryEvidenceReader`` carrying real canonical evidence
  (dependency readiness + rebuilt advisory validation, #1185/#1197).
  The controller no longer builds an empty, always-``UNAVAILABLE`` reader
  on its production path: an unbound reader cannot reconstruct an
  admissible candidate, so the bound factory binding is the production
  default, and the envelope's handoff/repository/issue/SHA are re-verified
  against the bound descriptor before any dispatch;
- the factory supplies the canonical repository-state verifier runner
  (``build_subprocess_verifier_runner``) inside the bound bootstrap;
- ``build_production_host_bootstrap`` composes the ``ProductionHostBootstrap``
  whose ``admission_providers()`` bind the descriptor loader, current
  resolver, host-local lease observer, and host clock;
- ``drive_fixed_codespace_pilot_on_host`` (shipped in #3635) runs the fixed
  read-only ``git rev-parse HEAD`` probe under the deterministic
  working-directory contract. Every admission decision stays in
  ``consume_fixed_codespace_pilot``.

The returned receipt -- completed or blocked -- is persisted atomically
(temp file + fsync + rename, then read-back verified) under
``$AGENT_OS_CHECKPOINT_STORE_ROOT/invocations/receipts/`` (a dedicated
subdirectory, so the top-level ``invocations/*.json`` descriptor invariant
that the existing handoff discovery relies on is never disturbed), and a
bounded receipt reference is emitted on stdout for the existing authorized
consumer. The controller performs no publication itself: publication stays
owned by the GitHub Service Agent through its existing governed paths.

Lease ownership: the fixed probe observes Scheduler leases and never
acquires them. This controller introduces no Scheduler lease acquire/release
behavior. It verifies the canonical ``$AGENT_OS_LEASE_DIRECTORY`` is the
single observed directory and fails closed when any active lease file is
present. One bounded exception, added for #3333 B10, is the fixed-pilot
dispatch claim: a distinct O_EXCL claim file (never a ``*.active.json``
Scheduler lease) acquired in the same lease directory before dispatch and
released only after verified receipt persistence, or on a failure
demonstrably before driver entry; it is preserved on every failure at
or after driver entry (F1). The claim is what makes
concurrent duplicate dispatch impossible -- the Scheduler guard alone is
observe-only and cannot fence a race. A claim left behind by a crash is
never stolen, expired, or bypassed: the next invocation fails closed with
``fixed-pilot-claim-ambiguous`` pending owner adjudication.

GCE reuse classification (standing directive): every component above is
*reuse* -- the GCE-derived execution architecture (authorization, admission,
lease observation, dispatch, receipt shape) applies unchanged. The only
Codespaces-specific behavior (the fixed pilot driver, the deterministic
workdir contract, the codespace selection) is already shipped. Nothing here
replaces the Scheduler, the authorization system, the lease manager, the
execution controller, or the receipt framework.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    ACCEPTED_REASON,
    ISSUE_NUMBER,
    OPERATION_ID,
    REPOSITORY,
    drive_fixed_codespace_pilot_on_host,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

from .host_github_read_transport import HostGitHubTransportUnavailable
from .invocation_completion_receipt import GOVERNED_ARTIFACT_PREFIX
from .production_governed_resume_factory import (
    ProductionGovernedResumeFactoryError,
    build_production_host_bootstrap_for_handoff,
)
from .production_host_bootstrap import (
    VERIFIER_RELATIVE_PATH,
    ProductionHostBootstrap,
    ProductionHostBootstrapError,
    ProductionHostConfiguration,
    build_production_host_bootstrap,
    load_production_host_configuration,
)
from .production_host_composition import read_canonical_codespace_selection

#: The only actor whose comment can admit the fixed pilot envelope.
ALLOWED_ACTOR = "Blummer92"
#: Host identity variable the codespace runtime always sets on the box itself.
HOST_SURFACE_ENV_VAR = "CODESPACE_NAME"
#: Receipt file layout owned by the controller under the store's invocations dir.
RECEIPT_FILE_PREFIX = "fixed-head-probe"
RECEIPT_SCHEMA_VERSION = "1.0"
#: The existing authorized consumer of the bounded receipt reference.
RECEIPT_CONSUMER = "github-service-agent-governed-publication-path"
#: Receipts live in this subdirectory of ``invocations/``, never as top-level
#: ``invocations/*.json``: the existing #1218 handoff discovery scans every
#: top-level ``*.json`` as a ``GovernedInvocationDescriptor``, so a foreign
#: receipt file there would poison discovery for the whole store. The
#: subdirectory follows the store's own on-demand-subdirectory convention
#: (``post-create.sh``: "the existing #1218 stores create their other
#: subdirectories on demand").
RECEIPTS_SUBDIR = "receipts"

_HANDOFF = re.compile(r"^executor-handoff:[0-9a-f]{64}$", re.ASCII)
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_COMPACT_UTC = re.compile(r"^\d{8}T\d{6}Z$", re.ASCII)
_ACTIVE_LEASE_FILE = re.compile(r"^[0-9a-f]{64}\.active\.json$", re.ASCII)
_MAX_EVENT_BYTES = 1_048_576


class Gate2ControllerError(RuntimeError):
    """Fail-closed evidence: the controller refused to proceed.

    Carries a machine-readable ``reason`` naming the failed gate; no
    credential, lease-holder, or host-secret material is ever attached.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        if type(reason) is not str or not reason:
            raise TypeError("reason must be non-empty text")
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Gate2ControllerResult:
    """Terminal outcome of one controller invocation."""

    status: str  # "completed" | "blocked" | "failed"
    reason_codes: tuple[str, ...] = ()
    receipt: dict[str, Any] | None = None
    receipt_path: str | None = None
    receipt_reference: dict[str, Any] | None = None


def _read_event_document(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Gate2ControllerError("event-document-unreadable", str(path)) from exc
    if len(raw) > _MAX_EVENT_BYTES:
        raise Gate2ControllerError("event-document-oversize", str(path))
    try:
        event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise Gate2ControllerError("event-document-malformed", str(path)) from exc
    if type(event) is not dict:
        raise Gate2ControllerError("event-document-malformed", str(path))
    return event


def _admit_envelope(event: dict[str, Any]) -> dict[str, Any]:
    """Admit the owner's comment through the canonical #1218 ingress.

    The only envelope the driver accepts is the one this reconstruction
    admits. Anything else -- wrong actor, wrong repository, wrong issue,
    unrecognized trigger body -- fails closed here, before any host binding
    is built or any credential is touched.
    """
    try:
        result = admit_issue_comment_event(
            event,
            expected_repository=REPOSITORY,
            allowed_actor=ALLOWED_ACTOR,
            run_attempt=1,
        )
    except (TypeError, ValueError) as exc:
        raise Gate2ControllerError("envelope-admission-error") from exc
    envelope = result.to_dict()
    if (
        envelope.get("status") != "accepted"
        or envelope.get("reason") != ACCEPTED_REASON
    ):
        raise Gate2ControllerError(
            "envelope-not-accepted",
            f"status={envelope.get('status')} reason={envelope.get('reason')}",
        )
    return envelope


def _require_real_directory(path: Path, name: str) -> Path:
    if path.is_symlink():
        raise Gate2ControllerError(f"{name}-is-symlink", str(path))
    if not path.is_dir():
        raise Gate2ControllerError(f"{name}-unavailable", str(path))
    return path


def _verify_host_bindings(
    configuration: ProductionHostConfiguration,
) -> Path:
    """Verify the four bound paths plus the initialized store layout.

    Every check is host-state only: absolute-path binding already happened in
    ``load_production_host_configuration``. The store's ``invocations/``
    directory must already exist -- initializing the checkpoint store is the
    owner's Gate 5 step, never the controller's.
    """
    _require_real_directory(
        configuration.checkpoint_store_root, "checkpoint-store-root"
    )
    _require_real_directory(configuration.repository_root, "repository-root")
    _require_real_directory(configuration.workspace_parent, "workspace-parent")
    _require_real_directory(configuration.lease_directory, "lease-directory")
    invocations = configuration.checkpoint_store_root / "invocations"
    if invocations.is_symlink() or not invocations.is_dir():
        raise Gate2ControllerError(
            "checkpoint-store-not-initialized",
            "invocations/ is missing under the bound store root (Gate 5)",
        )
    verifier = configuration.repository_root / VERIFIER_RELATIVE_PATH
    if not verifier.is_file() or verifier.is_symlink():
        raise Gate2ControllerError(
            "repository-identity-unverified",
            f"canonical verifier missing at {VERIFIER_RELATIVE_PATH}",
        )
    if not (configuration.repository_root / ".git").exists():
        raise Gate2ControllerError(
            "repository-identity-unverified", "no .git under the bound repository root"
        )
    return invocations


def _ensure_receipts_dir(invocations_dir: Path) -> Path:
    """Create the controller-owned receipts subdirectory on demand.

    Modeled on the store's own convention (``post-create.sh``: "#1218 stores
    create their other subdirectories on demand"). The directory is private
    (0700) and never a symlink; anything else fails closed.
    """
    receipts = invocations_dir / RECEIPTS_SUBDIR
    if receipts.is_symlink():
        raise Gate2ControllerError("receipts-dir-is-symlink", str(receipts))
    try:
        receipts.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise Gate2ControllerError("receipts-dir-unavailable", str(receipts)) from exc
    if not receipts.is_dir() or receipts.is_symlink():
        raise Gate2ControllerError("receipts-dir-unavailable", str(receipts))
    try:
        os.chmod(receipts, 0o700)
    except OSError as exc:
        raise Gate2ControllerError("receipts-dir-unavailable", str(receipts)) from exc
    return receipts


def _verify_execution_surface_identity(
    *,
    resolve_selection: Callable[[], object] | None,
    environ: Mapping[str, str],
) -> str:
    """Verify this host is the canonically selected execution surface.

    The canonical current-codespace selection (the same resolver the driver
    binds) must name one Available codespace, and this host's own
    ``CODESPACE_NAME`` must equal that name. A controller running anywhere
    else -- an unqualified host, a stale box, a different surface -- fails
    closed here and never reaches the pilot. Returns the selected
    codespace name so the B02 dispatch-evidence sink can compare a
    completed receipt's asserted codespace against it (#3333 B02).
    """
    selection = read_canonical_codespace_selection(resolve_selection)
    if (
        selection is None
        or getattr(selection, "selected", None) is not True
        or getattr(selection, "state", None) != "Available"
        or type(getattr(selection, "codespace_name", None)) is not str
        or not selection.codespace_name
    ):
        raise Gate2ControllerError("execution-surface-unqualified")
    host_name = environ.get(HOST_SURFACE_ENV_VAR)
    if type(host_name) is not str or not host_name.strip():
        raise Gate2ControllerError("host-surface-identity-unavailable")
    if host_name != selection.codespace_name:
        raise Gate2ControllerError("host-surface-identity-mismatch")
    return selection.codespace_name


def _fail_on_active_leases(lease_directory: Path) -> None:
    """Fail closed when any active lease file exists in the canonical directory.

    Observe-only: the controller never acquires, releases, or otherwise
    mutates lease state. The fixed probe itself never holds a lease, so any
    active lease file here means another governed process is mid-flight and
    this invocation must not proceed.
    """
    if lease_directory.is_symlink():
        raise Gate2ControllerError("lease-directory-is-symlink")
    try:
        entries = tuple(lease_directory.iterdir())
    except OSError as exc:
        raise Gate2ControllerError("lease-directory-unreadable") from exc
    for entry in entries:
        if entry.is_symlink():
            raise Gate2ControllerError("lease-directory-symlink-present", entry.name)
        if _ACTIVE_LEASE_FILE.fullmatch(entry.name) is not None:
            raise Gate2ControllerError("conflicting-active-lease", entry.name)


def _build_bound_bootstrap(
    envelope: dict[str, Any],
    configuration: ProductionHostConfiguration,
) -> ProductionHostBootstrap:
    """Build the production bootstrap bound to the admitted envelope.

    The factory loads the immutable handoff's runtime request, descriptor,
    and restart capsule from the same checkpoint store, verifies they bind
    the same subject, loads dependency readiness, and rebuilds the advisory
    validation result into a bound ``LiveRepositoryEvidenceReader``. This
    function then re-verifies the envelope itself against that bound
    record: a syntactically accepted comment naming a different handoff,
    repository, issue, or SHA than the durable record must not become an
    admitted candidate, and a missing or inconsistent record must fail
    here, before any dispatch or receipt. Expired evidence is not
    admitted either, but at the next layer: the bound reader returns
    UNAVAILABLE for it, and reconstruction therefore refuses admission;
    this binding function does not itself claim a candidate is admitted.
    """
    handoff = envelope.get("codespace_implementation_handoff_id_or_none")
    sha = envelope.get("codespace_implementation_sha_or_none")
    if type(handoff) is not str or _HANDOFF.fullmatch(handoff) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "handoff")
    if type(sha) is not str or _SHA40.fullmatch(sha) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "sha")
    try:
        bootstrap = build_production_host_bootstrap_for_handoff(
            handoff, configuration=configuration
        )
    except ProductionGovernedResumeFactoryError as exc:
        # Preserve the Gate 4 credential and host-configuration reasons
        # the old production path reported, instead of collapsing them
        # into generic bound evidence.
        cause = exc.__cause__
        while cause is not None:
            if isinstance(cause, HostGitHubTransportUnavailable):
                raise Gate2ControllerError(
                    "github-read-credential-unavailable",
                    "GITHUB_TOKEN or GH_TOKEN must be set (Gate 4)",
                ) from exc
            if isinstance(cause, ProductionHostBootstrapError):
                raise cause
            cause = cause.__cause__
        raise Gate2ControllerError("bound-evidence-unavailable") from exc
    request = bootstrap.runtime_request
    if request is None:
        raise Gate2ControllerError("bound-evidence-unavailable", "no runtime request")
    descriptor = request.invocation_descriptor
    if (
        descriptor.handoff_id != handoff
        or descriptor.repository != REPOSITORY
        or descriptor.issue_number != ISSUE_NUMBER
        or descriptor.source_sha != sha
    ):
        raise Gate2ControllerError("handoff-envelope-mismatch")
    try:
        providers = bootstrap.admission_providers()
        bound_descriptor = providers.descriptor_loader(handoff)
    except ProductionHostBootstrapError:
        raise
    except Exception as exc:
        raise Gate2ControllerError("bound-evidence-unavailable") from exc
    if (
        providers.evaluated_at != bootstrap.evaluated_at
        or bound_descriptor.handoff_id != handoff
        or bound_descriptor.repository != REPOSITORY
        or bound_descriptor.issue_number != ISSUE_NUMBER
        or bound_descriptor.source_sha != sha
    ):
        raise Gate2ControllerError("handoff-envelope-mismatch")
    return bootstrap


def _build_bootstrap(
    transports: tuple[Any, Any, Any, Any],
    configuration: ProductionHostConfiguration,
) -> ProductionHostBootstrap:
    (
        issue_transport,
        authorization_transport,
        repository_evidence_reader,
        run_verifier,
    ) = transports
    try:
        return build_production_host_bootstrap(
            issue_transport=issue_transport,
            authorization_transport=authorization_transport,
            repository_evidence_reader=repository_evidence_reader,
            run_verifier=run_verifier,
            configuration=configuration,
        )
    except Exception as exc:
        raise Gate2ControllerError("host-bootstrap-failed") from exc


def _validate_receipt_identity(envelope: dict[str, Any], receipt: dict[str, Any]) -> None:
    """Reject a receipt body contradicting the admitted envelope (#3333 X09).

    Identity is exact type AND value for every field: ``3333.0`` and
    ``True`` must not compare equal to the admitted integer ``3333``
    (Copilot R2), and a missing or non-string handoff/SHA/repository
    must not pass. The caller must pass the authoritative admitted
    envelope, never a driver-mutable copy (Copilot R1).
    """
    expected = {
        "handoff_id": envelope.get("codespace_implementation_handoff_id_or_none"),
        "expected_sha": envelope.get("codespace_implementation_sha_or_none"),
        "repository": envelope.get("repository"),
        "issue_number": envelope.get("issue_number"),
    }
    for field, value in expected.items():
        actual = receipt.get(field)
        if type(actual) is not type(value) or actual != value:
            raise Gate2ControllerError("receipt-identity-mismatch", field)


def _validate_completed_dispatch_evidence(
    envelope: dict[str, Any], receipt: dict[str, Any], codespace_name: str
) -> None:
    """Require dispatch evidence on a completed receipt (#3333 B02).

    Applies to freshly driven receipts AND to receipts found by the
    pre-dispatch scan, so a persisted completed receipt that never passed
    this sink cannot be laundered into authority by replay. Identity
    itself is checked by ``_validate_receipt_identity`` (or, for scanned
    receipts, by the scan's field match); this function checks that the
    completed outcome is backed by the fixed dispatch: exact integer
    exit zero, stdout exactly the expected SHA, neither stream
    truncated, argv exactly the fixed command, the asserted codespace
    equal to the selected surface, and non-empty invocation/descriptor
    identity strings.

    Honest limit, stated in the report as well: these fields are all
    self-reported by the driver, so a fully forged driver receipt that
    fabricates every field still passes this sink. The sink blocks
    driver-only or mismatched completions; it does not replace driver
    trust plus the independent receipt consumer's readback.
    """
    sha = envelope.get("codespace_implementation_sha_or_none")

    def _mismatch(field: str) -> Gate2ControllerError:
        return Gate2ControllerError("receipt-dispatch-evidence-mismatch", field)

    # The same completed-receipt sink handles fresh dispatch and both replay
    # scans. Refuse a different operation or receipt schema before success.
    for field, expected in (
        ("schema_version", RECEIPT_SCHEMA_VERSION),
        ("operation_id", OPERATION_ID),
    ):
        actual = receipt.get(field)
        if type(actual) is not str or actual != expected:
            raise _mismatch(field)
    if type(receipt.get("exit_status")) is not int or receipt.get("exit_status") != 0:
        raise _mismatch("exit_status")
    stdout = receipt.get("stdout_tail")
    if type(stdout) is not str or stdout.strip() != sha:
        raise _mismatch("stdout_tail")
    if receipt.get("stdout_truncated") is not False:
        raise _mismatch("stdout_truncated")
    if receipt.get("stderr_truncated") is not False:
        raise _mismatch("stderr_truncated")
    if receipt.get("argv") != ["git", "rev-parse", "HEAD"]:
        raise _mismatch("argv")
    if type(receipt.get("codespace_name")) is not str or receipt.get("codespace_name") != codespace_name:
        raise _mismatch("codespace_name")
    for field in ("admission_id", "invocation_id", "descriptor_id"):
        value = receipt.get(field)
        if type(value) is not str or not value:
            raise _mismatch(field)


def _claim_digest(envelope: dict[str, Any]) -> str:
    """Stable operation identity for the fixed-pilot dispatch claim (B10).

    Domain-separated from every Scheduler lease identity: the claim is
    keyed by handoff + expected SHA only, because the fixed pilot has no
    Scheduler branch/workspace/projection/approval to bind, and inventing
    those would be an unsafe lease mapping. The same envelope therefore
    always maps to the same claim file, which is what makes the O_EXCL
    acquisition a correct at-most-once fence for this operation.
    """
    handoff = envelope.get("codespace_implementation_handoff_id_or_none")
    sha = envelope.get("codespace_implementation_sha_or_none")
    if type(handoff) is not str or _HANDOFF.fullmatch(handoff) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "handoff")
    if type(sha) is not str or _SHA40.fullmatch(sha) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "sha")
    return hashlib.sha256(
        f"gate2-fixed-pilot-claim-v1\n{handoff}\n{sha}".encode("utf-8")
    ).hexdigest()


def _acquire_fixed_pilot_claim(
    lease_directory: Path, envelope: dict[str, Any], evaluated_at: str
) -> Path:
    """Atomically claim one dispatch of the fixed pilot (B10).

    O_EXCL creation: two concurrent controller processes racing the same
    envelope both pass the observe-only Scheduler lease guard and the
    receipt scan, but only one creates the claim file; the loser fails
    closed with ``fixed-pilot-claim-ambiguous`` and never dispatches.
    A claim left behind by a crash is never removed here -- removal
    would turn an uncertain outcome into implicit takeover. The next
    invocation then fails closed with the same reason pending owner
    adjudication (verify no dispatch is in flight, then remove the file
    by hand). The claim file is deliberately NOT a ``*.active.json``
    Scheduler lease, so the Scheduler guard's semantics are unchanged.
    """
    path = lease_directory / f"gate2-fixed-pilot-claim-{_claim_digest(envelope)}.json"
    payload = json.dumps(
        {
            "domain": "gate2-fixed-pilot-claim-v1",
            "handoff_id": envelope.get("codespace_implementation_handoff_id_or_none"),
            "expected_sha": envelope.get("codespace_implementation_sha_or_none"),
            "claimed_at": evaluated_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Gate2ControllerError("fixed-pilot-claim-ambiguous", path.name) from exc
    except OSError as exc:
        raise Gate2ControllerError("fixed-pilot-claim-failed", path.name) from exc
    # An O_EXCL-created claim is ours only while its path still names the
    # same inode as the descriptor returned by os.open. A failed setup never
    # enters the driver, so it may be rolled back, but not by blind unlink.
    created_stat = None
    setup_error = None
    try:
        created_stat = os.fstat(fd)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("claim write made no progress")
            view = view[written:]
        os.fsync(fd)
    except OSError as exc:
        setup_error = exc
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            if setup_error is None:
                setup_error = exc
    if setup_error is not None:
        try:
            current_stat = path.lstat()
            if (
                created_stat is None
                or (current_stat.st_dev, current_stat.st_ino)
                != (created_stat.st_dev, created_stat.st_ino)
            ):
                raise Gate2ControllerError("fixed-pilot-claim-ambiguous", path.name)
            path.unlink()
        except OSError as exc:
            raise Gate2ControllerError("fixed-pilot-claim-ambiguous", path.name) from exc
        raise Gate2ControllerError("fixed-pilot-claim-failed", path.name) from setup_error
    return path


def _release_fixed_pilot_claim(path: Path) -> None:
    """Release a claim in exactly two cases (F1 claim lifecycle).

    Called (a) after verified receipt persistence on the success path,
    and (b) on a failure demonstrably before driver entry (the caller
    proves this with ``may_have_dispatched`` still false). It is NEVER
    called from an unconditional ``finally:`` after driver entry: on
    any post-invoke failure the claim is preserved so the next
    invocation fails closed with ``fixed-pilot-claim-ambiguous``
    before any dispatch.

    Best-effort by design: on the success path the receipt is already
    durable, and the pre-dispatch scan runs before any claim
    acquisition, so a stale claim file can never block the return of
    an already-persisted completed receipt -- it can only block a
    fresh attempt for an envelope with no completed receipt, which is
    exactly the safe crash semantic. Release failures are therefore
    swallowed, never allowed to turn a persisted receipt into a
    reported failure.
    """
    try:
        path.unlink()
    except OSError:
        pass


def _find_completed_receipt(
    receipts_dir: Path, envelope: dict[str, Any], codespace_name: str
) -> tuple[Path, dict[str, Any]] | None:
    """Pre-dispatch replay return by receipt BODY identity (#3333 B10).

    Filenames embed ``evaluated_at`` timestamps, so a filename check
    cannot dedup across seconds. This scan reads every receipt body and
    matches handoff + SHA + repository + issue + completed status.
    A completed match is returned WITHOUT re-dispatch; a blocked prior
    receipt does not block a new attempt. An unreadable or malformed
    store fails closed (``receipt-store-unreadable``) rather than
    dispatching on uncertain state, and a matched completed receipt
    that fails the B02 sink fails closed with
    ``receipt-dispatch-evidence-mismatch`` instead of being laundered.

    Two filename namespaces are skipped without being read, because they
    are never this scan's evidence: files owned by the governed-resume
    store (``governed-resume-`` prefix — its receipts and any leftover
    governed temp files) and temp files (``.tmp-`` prefix). A malformed
    governed receipt therefore cannot break this probe's scan, and a
    leftover temp file cannot either (the governed store also writes
    temps with a ``.tmp`` suffix now, so new leftovers are not ``.json``
    at all). Everything else keeps the established fail-closed behavior:
    a malformed or symlinked file under any other name still raises
    ``receipt-store-unreadable``, and a well-formed foreign completed
    receipt is still rejected by the identity/operation sink (#3765).
    Skipping governed files cannot launder a dispatch: the scan only
    ever returns a body-identical probe receipt, and a governed-named
    file is never returned.
    """
    try:
        entries = sorted(receipts_dir.iterdir())
    except OSError as exc:
        raise Gate2ControllerError("receipt-store-unreadable") from exc
    for entry in entries:
        if entry.suffix != ".json":
            continue
        if entry.name.startswith(GOVERNED_ARTIFACT_PREFIX) or entry.name.startswith(
            ".tmp-"
        ):
            continue
        if entry.is_symlink():
            raise Gate2ControllerError("receipt-store-unreadable", entry.name)
        try:
            raw = entry.read_bytes()
        except OSError as exc:
            raise Gate2ControllerError("receipt-store-unreadable", entry.name) from exc
        try:
            receipt = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise Gate2ControllerError("receipt-store-unreadable", entry.name) from exc
        if type(receipt) is not dict:
            raise Gate2ControllerError("receipt-store-unreadable", entry.name)
        expected = {
            "handoff_id": envelope.get("codespace_implementation_handoff_id_or_none"),
            "expected_sha": envelope.get("codespace_implementation_sha_or_none"),
            "repository": envelope.get("repository"),
            "issue_number": envelope.get("issue_number"),
        }
        if receipt.get("status") != "completed":
            continue
        # F1/P10: same claim identity (handoff + SHA) but changed immutable
        # intent (repository / issue) is a conflict, not a new attempt:
        # fail closed instead of silently dispatching under a reused
        # identity or treating the receipt as reusable. Receipts for a
        # different handoff or SHA are unrelated and are skipped.
        identity_fields = ("handoff_id", "expected_sha")
        identity_matched = all(
            type(receipt.get(field)) is type(expected[field])
            and receipt.get(field) == expected[field]
            for field in identity_fields
        )
        matched = True
        for field, value in expected.items():
            actual = receipt.get(field)
            if type(actual) is not type(value) or actual != value:
                matched = False
                break
        if identity_matched and not matched:
            conflicting = next(
                field
                for field in ("repository", "issue_number")
                if type(receipt.get(field)) is not type(expected[field])
                or receipt.get(field) != expected[field]
            )
            raise Gate2ControllerError("receipt-identity-conflict", conflicting)
        if not matched:
            continue
        _validate_completed_dispatch_evidence(envelope, receipt, codespace_name)
        return entry, receipt
    return None


def _receipt_file_name(envelope: dict[str, Any], evaluated_at: str) -> str:
    handoff = envelope.get("codespace_implementation_handoff_id_or_none")
    sha = envelope.get("codespace_implementation_sha_or_none")
    if type(handoff) is not str or _HANDOFF.fullmatch(handoff) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "handoff")
    if type(sha) is not str or _SHA40.fullmatch(sha) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "sha")
    if type(evaluated_at) is not str:
        raise Gate2ControllerError("receipt-identity-invalid", "evaluated_at")
    compact = evaluated_at.replace("-", "").replace(":", "")
    if _COMPACT_UTC.fullmatch(compact) is None:
        raise Gate2ControllerError("receipt-identity-invalid", "evaluated_at")
    digest = handoff.removeprefix("executor-handoff:")
    return f"{RECEIPT_FILE_PREFIX}-{digest}-{sha}-{compact}.json"


def _persist_receipt_atomically(
    invocations_dir: Path, name: str, receipt: dict[str, Any]
) -> Path:
    """Write the receipt with temp-file + fsync + rename, then read-back verify."""
    if type(receipt) is not dict:
        raise Gate2ControllerError("receipt-not-a-mapping")
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
    final = invocations_dir / name
    if final.exists() or final.is_symlink():
        raise Gate2ControllerError("receipt-already-exists", name)
    tmp = invocations_dir / (name + ".tmp")
    if tmp.exists() or tmp.is_symlink():
        raise Gate2ControllerError("receipt-tmp-ambiguous", name)
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise Gate2ControllerError("receipt-write-failed", name) from exc
    try:
        data = payload.encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except OSError as exc:
        raise Gate2ControllerError("receipt-write-failed", name) from exc
    finally:
        os.close(fd)
    try:
        os.replace(tmp, final)
        dir_fd = os.open(str(invocations_dir), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise Gate2ControllerError("receipt-write-failed", name) from exc
    try:
        read_back = json.loads(final.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Gate2ControllerError("receipt-readback-failed", name) from exc
    if read_back != receipt:
        raise Gate2ControllerError("receipt-readback-mismatch", name)
    return final


def _receipt_reference(
    receipt_path: Path, envelope: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    """Bounded reference for the authorized consumer label (no verified module wired here).

    Carries identity and outcome only -- no stdout/stderr tails, no host
    paths beyond the receipt's own location. Publication itself stays with
    the GitHub Service Agent through its existing governed paths.
    """
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "operation_id": OPERATION_ID,
        "repository": REPOSITORY,
        "issue_number": ISSUE_NUMBER,
        "receipt_path": str(receipt_path),
        "handoff_id": envelope.get("codespace_implementation_handoff_id_or_none"),
        "expected_sha": envelope.get("codespace_implementation_sha_or_none"),
        "status": receipt.get("status"),
        "reason_codes": list(receipt.get("reason_codes") or []),
        "consumer": RECEIPT_CONSUMER,
    }


def run_gate2_fixed_pilot_controller(
    *,
    event_path: str | Path,
    environ: Mapping[str, str] | None = None,
    drive: Callable[..., dict[str, Any]] | None = None,
    resolve_selection: Callable[[], object] | None = None,
    build_transports: Callable[[], tuple[Any, Any, Any, Any]] | None = None,
) -> Gate2ControllerResult:
    """Run the Gate 2 fixed-pilot controller end to end, fail-closed.

    ``event_path`` is the owner's issue-comment event document (the
    per-invocation CURRENT authorization comment). ``drive``,
    ``resolve_selection``, and ``build_transports`` are dependency-injection
    seams for offline tests; production callers leave them unset, and
    unset ``build_transports`` now means the bound factory bootstrap
    (never an empty evidence reader). A test-supplied ``build_transports``
    still exercises the old bootstrap composition path in isolation; it
    is not the production path, and the bound-path integration tests
    prove the production default separately.
    """
    source = os.environ if environ is None else environ
    invoke = drive if drive is not None else drive_fixed_codespace_pilot_on_host

    try:
        envelope = _admit_envelope(_read_event_document(Path(event_path)))
        configuration = load_production_host_configuration(source)
        invocations_dir = _verify_host_bindings(configuration)
        selected_name = _verify_execution_surface_identity(
            resolve_selection=resolve_selection, environ=source
        )
        _fail_on_active_leases(configuration.lease_directory)
        if build_transports is not None:
            bootstrap = _build_bootstrap(build_transports(), configuration)
        else:
            bootstrap = _build_bound_bootstrap(envelope, configuration)
        # The receipts directory is ensured BEFORE the pilot drives: the fixed
        # probe consumes a governed invocation, so its receipt must have a
        # durable home before any execution occurs. A post-drive failure here
        # would lose the receipt of an already-consumed probe.
        receipts_dir = _ensure_receipts_dir(invocations_dir)

        # B10 sequential replay: a completed receipt body for this exact
        # envelope is returned WITHOUT re-dispatch, even across seconds
        # (filenames carry timestamps and cannot dedup). This runs
        # before any claim acquisition, so a stale claim left by a
        # crash can never block the return of an already-persisted
        # completed receipt.
        existing = _find_completed_receipt(receipts_dir, envelope, selected_name)
        if existing is not None:
            existing_path, existing_receipt = existing
            existing_reasons = existing_receipt.get("reason_codes")
            if (
                type(existing_reasons) is not list
                or not existing_reasons
                or any(type(r) is not str or not r for r in existing_reasons)
            ):
                raise Gate2ControllerError("receipt-reason-codes-invalid")
            return Gate2ControllerResult(
                status="completed",
                reason_codes=tuple(existing_reasons),
                receipt=existing_receipt,
                receipt_path=str(existing_path),
                receipt_reference=_receipt_reference(
                    existing_path, envelope, existing_receipt
                ),
            )

        # B10 atomic claim: acquired after the Scheduler lease guard and
        # the replay scan. F1 claim lifecycle: entry into ``invoke`` is
        # MAY-HAVE-DISPATCHED. The claim is released ONLY in two cases:
        # (a) a failure demonstrably BEFORE driver entry (nothing below
        # has invoked the driver, proven by ``may_have_dispatched`` still
        # false -- today only the envelope deepcopy sits in that window),
        # or (b) success, after an identity-bound receipt was persisted
        # AND verified by canonical readback. Every other failure --
        # driver throw, bad result shape, identity mismatch, evidence
        # mismatch, receipt write/fsync/rename/readback failure, or an
        # unknown exception after driver entry -- PRESERVES the claim:
        # the next invocation then fails closed with
        # ``fixed-pilot-claim-ambiguous`` before any dispatch, and the
        # original failure reason is still reported for this run. The
        # claim file itself is the ambiguous-outcome marker; it is never
        # stolen, expired, or bypassed, so a retry can never silently
        # dispatch again. (An unconditional ``finally:`` release here was
        # the F1 defect: it deleted that marker on every failure.)
        claim_path = _acquire_fixed_pilot_claim(
            configuration.lease_directory, envelope, bootstrap.evaluated_at
        )
        # QF-1 post-acquisition re-scan: the pre-scan above ran before
        # this claim existed, so a winner that completed while this
        # caller was stalled between scan and acquisition would be
        # invisible to it. Re-running the same body-identity scan while
        # holding the newly acquired claim closes that window: a
        # matching completed receipt is returned WITHOUT a new dispatch
        # (a loser is ambiguous before persistence OR same-path replay
        # after it -- never assumed ambiguous in both cases). Only a
        # validated matching receipt releases this claim; any scan
        # error (unreadable store, identity conflict, sink mismatch,
        # invalid reason codes) propagates WITHOUT releasing it, so the
        # outcome stays fail-closed and ambiguous rather than silently
        # cleared. The scan compares handoff + SHA + repository + issue
        # from the receipt body; attempt is not a receipt field and is
        # not compared. The operation ID and schema version are compared
        # by the shared completed-receipt sink the scan invokes for each
        # matched receipt.
        rescan = _find_completed_receipt(receipts_dir, envelope, selected_name)
        if rescan is not None:
            rescan_path, rescan_receipt = rescan
            rescan_reasons = rescan_receipt.get("reason_codes")
            if (
                type(rescan_reasons) is not list
                or not rescan_reasons
                or any(type(r) is not str or not r for r in rescan_reasons)
            ):
                raise Gate2ControllerError("receipt-reason-codes-invalid")
            _release_fixed_pilot_claim(claim_path)
            return Gate2ControllerResult(
                status="completed",
                reason_codes=tuple(rescan_reasons),
                receipt=rescan_receipt,
                receipt_path=str(rescan_path),
                receipt_reference=_receipt_reference(
                    rescan_path, envelope, rescan_receipt
                ),
            )
        may_have_dispatched = False
        try:
            # Copilot R1: the driver must never receive the authoritative
            # envelope. It gets a deep copy, so mutating its input (including
            # any nested value, if the ingress shape ever gains one) cannot
            # rewrite the identity used below for validation, the receipt
            # filename, and the receipt reference. The admitted envelope is
            # flat scalars today (ingress ``to_dict``), so a shallow copy
            # would suffice now; deepcopy is the smallest option that stays
            # sound if that shape changes.
            payload = copy.deepcopy(envelope)
            may_have_dispatched = True
            receipt = invoke(payload, bootstrap=bootstrap)
            if type(receipt) is not dict:
                raise Gate2ControllerError("driver-returned-non-mapping")
            raw_reason_codes = receipt.get("reason_codes")
            if type(raw_reason_codes) is not list or not raw_reason_codes:
                raise Gate2ControllerError("receipt-reason-codes-invalid")
            validated_reason_codes: list[str] = []
            for raw_reason_code in raw_reason_codes:
                if type(raw_reason_code) is not str or not raw_reason_code:
                    raise Gate2ControllerError("receipt-reason-codes-invalid")
                validated_reason_codes.append(raw_reason_code)
            reason_codes = tuple(validated_reason_codes)
            _validate_receipt_identity(envelope, receipt)
            if receipt.get("status") == "completed":
                _validate_completed_dispatch_evidence(
                    envelope, receipt, selected_name
                )
            name = _receipt_file_name(envelope, bootstrap.evaluated_at)
            receipt_path = _persist_receipt_atomically(receipts_dir, name, receipt)
        except BaseException:
            if not may_have_dispatched:
                _release_fixed_pilot_claim(claim_path)
            raise
        else:
            _release_fixed_pilot_claim(claim_path)
    except Gate2ControllerError:
        raise
    except ProductionHostBootstrapError as exc:
        raise Gate2ControllerError("host-configuration-invalid", str(exc)) from exc
    except HostGitHubTransportUnavailable as exc:
        raise Gate2ControllerError(
            "github-read-credential-unavailable",
            "GITHUB_TOKEN or GH_TOKEN must be set (Gate 4)",
        ) from exc
    except Exception as exc:
        raise Gate2ControllerError("unexpected-controller-error") from exc
    reference = _receipt_reference(receipt_path, envelope, receipt)

    status = "completed" if receipt.get("status") == "completed" else "blocked"
    return Gate2ControllerResult(
        status=status,
        reason_codes=reason_codes,
        receipt=receipt,
        receipt_path=str(receipt_path),
        receipt_reference=reference,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: ``gate2-controller --event <owner-comment-event.json>``."""
    parser = argparse.ArgumentParser(
        description=(
            "Gate 2 (#3333) production-host controller: admit one owner "
            "codespace-implementation comment and drive the fixed HEAD pilot."
        )
    )
    parser.add_argument(
        "--event",
        type=Path,
        required=True,
        help="Path to the owner's issue-comment event JSON document.",
    )
    args = parser.parse_args(argv)
    try:
        result = run_gate2_fixed_pilot_controller(event_path=args.event)
    except Gate2ControllerError as exc:
        print(
            json.dumps(
                {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "operation_id": OPERATION_ID,
                    "status": "failed",
                    "reason_codes": [exc.reason],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    # The bounded receipt reference is the only stdout contract, for the
    # existing authorized consumer.
    print(json.dumps(result.receipt_reference, sort_keys=True))
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
