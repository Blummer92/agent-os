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
- ``build_host_github_read_transport_from_environment`` supplies the one
  read-only host transport satisfying both the single-issue and the
  execution-authorization-source protocols (#1319);
- ``LiveRepositoryEvidenceReader()`` is the truthful always-``UNAVAILABLE``
  #1155 reader until structured evidence is supplied through the canonical
  AOS-GCE2F owners; the bootstrap deliberately supplies no default evidence
  source;
- ``build_subprocess_verifier_runner`` is the canonical repository-state
  verifier runner;
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

Lease ownership: the fixed probe observes leases and never acquires them.
This controller introduces no lease acquire/release behavior. It verifies the
canonical ``$AGENT_OS_LEASE_DIRECTORY`` is the single observed directory and
fails closed when any active lease file is present.

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

from .host_github_read_transport import (
    HostGitHubTransportUnavailable,
    build_host_github_read_transport_from_environment,
)
from .production_host_bootstrap import (
    VERIFIER_RELATIVE_PATH,
    ProductionHostBootstrap,
    ProductionHostBootstrapError,
    ProductionHostConfiguration,
    build_production_host_bootstrap,
    build_subprocess_verifier_runner,
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
) -> None:
    """Verify this host is the canonically selected execution surface.

    The canonical current-codespace selection (the same resolver the driver
    binds) must name one Available codespace, and this host's own
    ``CODESPACE_NAME`` must equal that name. A controller running anywhere
    else -- an unqualified host, a stale box, a different surface -- fails
    closed here and never reaches the pilot.
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


def _default_transports() -> tuple[Any, Any, Any, Any]:
    """Build the production transports. Fail closed on missing credential."""
    try:
        host_transport = build_host_github_read_transport_from_environment()
    except HostGitHubTransportUnavailable as exc:
        raise Gate2ControllerError(
            "github-read-credential-unavailable",
            "GITHUB_TOKEN or GH_TOKEN must be set (Gate 4)",
        ) from exc
    from scripts.agent_os_candidate_packet_live_input import (
        LiveRepositoryEvidenceReader,
    )

    return (
        host_transport,  # issue_transport (read-only SingleIssueTransport)
        host_transport,  # authorization_transport (same #1319 dual-protocol object)
        LiveRepositoryEvidenceReader(),  # truthful always-UNAVAILABLE #1155 reader
        build_subprocess_verifier_runner(),
    )


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
    """Bounded reference for the existing authorized consumer.

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
    seams for offline tests; production callers leave them unset.
    """
    source = os.environ if environ is None else environ
    invoke = drive if drive is not None else drive_fixed_codespace_pilot_on_host
    make_transports = (
        build_transports if build_transports is not None else _default_transports
    )

    try:
        envelope = _admit_envelope(_read_event_document(Path(event_path)))
        configuration = load_production_host_configuration(source)
        invocations_dir = _verify_host_bindings(configuration)
        _verify_execution_surface_identity(
            resolve_selection=resolve_selection, environ=source
        )
        _fail_on_active_leases(configuration.lease_directory)
        bootstrap = _build_bootstrap(make_transports(), configuration)
        # The receipts directory is ensured BEFORE the pilot drives: the fixed
        # probe consumes a governed invocation, so its receipt must have a
        # durable home before any execution occurs. A post-drive failure here
        # would lose the receipt of an already-consumed probe.
        receipts_dir = _ensure_receipts_dir(invocations_dir)

        receipt = invoke(envelope, bootstrap=bootstrap)
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
        name = _receipt_file_name(envelope, bootstrap.evaluated_at)
        receipt_path = _persist_receipt_atomically(receipts_dir, name, receipt)
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
