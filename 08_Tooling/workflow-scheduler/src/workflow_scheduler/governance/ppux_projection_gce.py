"""Fixed GitHub-to-GCE transport for PPUX prompt projection (#2673).

Registers the fixed ``ppux-picture-perfect-prompt-projection`` operation
promised by the #2525 transport contract: the projection trigger carries an
exact branch, a 40-hex source SHA, and a 64-hex input identity; the host
invokes only ``src/promptProjectionEntrypoint.ts`` /
``projectTutorialPromptCards(...)`` under the qualified Node 22 runtime; the
structured recorder validates the picture-perfect-prompt-projection-result-v1
payload before it becomes governed evidence.

Mirrors the existing dev-validation transport's lifecycle (policy-gated claims
-> VM lifecycle -> fixed host command over IAP SSH -> framed payload ->
structured recorder) and its finite reason vocabulary. The existing
``ppux-picture-perfect-ts-vitest`` validation profile is untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from .gce_control_path import VmState
from .gce_gcloud_adapter import (
    GcloudIapAdapter,
    RESOURCE,
    _policy,
)
from .github_issue_comment_ingress import INGRESS_SCHEMA_VERSION, IssueCommentIngressResult

FRAME_START = "PPUX-PROJECTION-FRAME-START"
FRAME_END = "PPUX-PROJECTION-FRAME-END"

HOST_PYTHON = "/usr/bin/python3"
REPOSITORY = "Blummer92/agent-os"
PPUX_PROJECTION_OPERATION_ID = "ppux-picture-perfect-prompt-projection"
PPUX_PROJECTION_ENTRYPOINT_MODULE = "agent_os_execution_service.ppux_projection_entrypoint"
PPUX_PROJECTION_SCHEMA_VERSION = "1.0"
PROJECTION_RESULT_VERSION = "picture-perfect-prompt-projection-result-v1"

GCE_PPUX_PROJECTION_TRANSPORT_TIMEOUT_SECONDS = 420

#: Finite structured payload admission bounds. An output that exceeds any
#: admitted bound fails closed with projection-output-oversize; partial or
#: tail-truncated JSON is never returned as canonical projection evidence.
MAX_PROJECTION_RESULT_BYTES = 256 * 1024
MAX_PROJECTION_CARDS = 200
MAX_DIAGNOSTIC_CHARS = 4096
MAX_DIAGNOSTIC_FIELDS = 16

_BRANCH_RE = re.compile(r"^agent/(?!main$)[A-Za-z0-9._/-]{1,180}$", re.ASCII)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_INPUT_REF_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_REQUEST_ID_RE = re.compile(r"^ppux-projection-[A-Za-z0-9-]{1,64}$", re.ASCII)

_AUTHORITY_FIELDS = (
    "executionAuthorized",
    "externalWriteAuthorized",
    "productionAuthorized",
)


@dataclass(frozen=True)
class PpuxProjectionRequest:
    repository: str
    issue_number: int
    branch: str
    source_sha: str
    input_ref: str
    request_id: str
    operation_id: Literal["ppux-picture-perfect-prompt-projection"]


class PpuxProjectionRecorderError(Exception):
    """A structured-recorder violation; ``reason`` is the finite reason code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _invalid(message: str) -> ValueError:
    return ValueError(f"Invalid PPUX projection request: {message}")


def build_ppux_projection_request(
    *,
    repository: str,
    issue_number: int,
    branch: str,
    source_sha: str,
    input_ref: str,
    request_id: str,
) -> PpuxProjectionRequest:
    """Validate the fixed projection request surface; raise on any deviation.

    The operation id is fixed: the caller cannot ask for a different host
    operation through this transport.
    """
    if repository != REPOSITORY:
        raise _invalid(f"repository must be {REPOSITORY!r}")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        raise _invalid("issue_number must be a positive integer")
    if not isinstance(branch, str) or not _BRANCH_RE.fullmatch(branch):
        raise _invalid("branch must be an agent/* development branch")
    if branch in {"agent/", "agent/main"} or ".." in branch or "//" in branch:
        raise _invalid("branch must be an agent/* development branch")
    if branch.endswith("/") or branch.endswith("."):
        raise _invalid("branch must be an agent/* development branch")
    if not isinstance(source_sha, str) or not _SHA_RE.fullmatch(source_sha):
        raise _invalid("source_sha must be a 40-character lowercase hex SHA")
    if not isinstance(input_ref, str) or not _INPUT_REF_RE.fullmatch(input_ref):
        raise _invalid("input_ref must be a 64-character lowercase hex content identity")
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise _invalid("request_id must match ppux-projection-[A-Za-z0-9-]{1,64}")
    return PpuxProjectionRequest(
        repository=repository,
        issue_number=issue_number,
        branch=branch,
        source_sha=source_sha,
        input_ref=input_ref,
        request_id=request_id,
        operation_id=PPUX_PROJECTION_OPERATION_ID,
    )


def ppux_projection_host_command(request: PpuxProjectionRequest) -> str:
    """Return the single fixed host command for this request.

    The argv is fixed apart from the validated request identities: no
    caller-controlled module, script, or shell fragment can ride along.
    """
    argv = (
        HOST_PYTHON,
        "-m",
        PPUX_PROJECTION_ENTRYPOINT_MODULE,
        "--repository",
        request.repository,
        "--issue-number",
        str(request.issue_number),
        "--branch",
        request.branch,
        "--source-sha",
        request.source_sha,
        "--input-ref",
        request.input_ref,
        "--request-id",
        request.request_id,
        "--operation-id",
        request.operation_id,
    )
    return shlex.join(argv)


def _failure(request: PpuxProjectionRequest, reason: str) -> dict[str, object]:
    """Finite blocked envelope: never authorizes, never claims side effects."""
    return {
        "schema_version": PPUX_PROJECTION_SCHEMA_VERSION,
        "status": "needs-decision",
        "reason_codes": [reason],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "input_ref": request.input_ref,
        "operation_id": request.operation_id,
        "request_id": request.request_id,
        "cleanup_complete": False,
        "workspace_side_effects_performed": False,
        "external_side_effects_performed": False,
        "production_state_mutated": False,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "merge_authorized": False,
    }


def _lifecycle_failure(
    request: PpuxProjectionRequest,
    reason: str,
    *,
    initial_state: VmState | None = None,
    start_issued: bool = False,
) -> dict[str, object]:
    evidence = _failure(request, reason)
    evidence.update(
        {
            "vm_initial_state": None if initial_state is None else initial_state.value,
            "start_issued": start_issued,
            "shutdown_issued": False,
        }
    )
    return evidence


def _ssh_failure(request: PpuxProjectionRequest, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    envelope = _failure(request, "projection-ssh-failed")
    envelope["ssh_exit_code"] = completed.returncode
    return envelope


def _bounded_tail(value: object) -> str:
    if not isinstance(value, str):
        raise PpuxProjectionRecorderError("projection-diagnostic-invalid")
    if len(value) > MAX_DIAGNOSTIC_CHARS:
        raise PpuxProjectionRecorderError("projection-diagnostic-oversize")
    return value


def record_ppux_projection_result(
    payload: Mapping[str, object], request: PpuxProjectionRequest
) -> dict[str, object]:
    """Validate and record the structured projection evidence.

    The canonical picture-perfect-prompt-projection-result-v1 payload is
    preserved verbatim (no truncation, no rewriting). Diagnostics live under
    the separate ``diagnostics`` key and never inside the canonical result.
    Any shape, identity, authority, or bound violation raises
    :class:`PpuxProjectionRecorderError` with a finite reason instead of
    returning partial evidence.
    """
    if not isinstance(payload, dict):
        raise PpuxProjectionRecorderError("projection-evidence-invalid")

    identity_fields = {
        "repository": request.repository,
        "issue_number": request.issue_number,
        "branch": request.branch,
        "tested_sha": request.source_sha,
        "operation_id": request.operation_id,
        "input_ref": request.input_ref,
        "request_id": request.request_id,
    }
    for key, expected in identity_fields.items():
        if payload.get(key) != expected:
            raise PpuxProjectionRecorderError("projection-evidence-identity-mismatch")

    status = payload.get("status")
    if status not in {"success", "blocked", "needs-decision"}:
        raise PpuxProjectionRecorderError("projection-status-invalid")

    reason_codes = payload.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(isinstance(code, str) for code in reason_codes):
        raise PpuxProjectionRecorderError("projection-reason-invalid")

    result = payload.get("projection_result")
    if status == "success":
        if not isinstance(result, dict):
            raise PpuxProjectionRecorderError("projection-result-invalid")
        if result.get("formatVersion") != PROJECTION_RESULT_VERSION:
            raise PpuxProjectionRecorderError("projection-result-invalid")
        if result.get("status") not in {"valid", "blocked"}:
            raise PpuxProjectionRecorderError("projection-result-invalid")
        canonical_bytes = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(canonical_bytes) > MAX_PROJECTION_RESULT_BYTES:
            raise PpuxProjectionRecorderError("projection-output-oversize")
        package = result.get("package")
        if package is not None:
            if not isinstance(package, dict):
                raise PpuxProjectionRecorderError("projection-result-invalid")
            cards = package.get("cards")
            if isinstance(cards, list) and len(cards) > MAX_PROJECTION_CARDS:
                raise PpuxProjectionRecorderError("projection-output-oversize")
            for field in _AUTHORITY_FIELDS:
                if package.get(field) is not False:
                    raise PpuxProjectionRecorderError("projection-authority-violation")
        if not isinstance(result.get("blockers"), list):
            raise PpuxProjectionRecorderError("projection-result-invalid")

    diagnostics = payload.get("diagnostics")
    if diagnostics is not None:
        if not isinstance(diagnostics, dict) or len(diagnostics) > MAX_DIAGNOSTIC_FIELDS:
            raise PpuxProjectionRecorderError("projection-diagnostic-invalid")
        for field, value in diagnostics.items():
            diagnostics[field] = _bounded_tail(value)
    # Diagnostics stay separate: the canonical result must not carry them.
    if isinstance(result, dict) and "diagnostics" in result:
        raise PpuxProjectionRecorderError("projection-diagnostic-invalid")

    recorded = dict(payload)
    recorded["schema_version"] = PPUX_PROJECTION_SCHEMA_VERSION
    recorded["cleanup_complete"] = bool(payload.get("cleanup_complete", False))
    for authority_field in (
        "workspace_side_effects_performed",
        "external_side_effects_performed",
        "production_state_mutated",
        "execution_authorized",
        "scheduler_invoked",
        "publication_invoked",
        "merge_authorized",
    ):
        if payload.get(authority_field) is not False:
            raise PpuxProjectionRecorderError("projection-authority-violation")
        recorded[authority_field] = False
    return recorded


def _extract_framed_payload(stdout: object) -> tuple[str | None, str | None]:
    """Extract the single framed JSON payload; finite reason on any deviation."""
    if type(stdout) is not str or stdout.count(FRAME_START) != 1 or stdout.count(FRAME_END) != 1:
        return None, "projection-frame-invalid"
    start = stdout.find(FRAME_START)
    end = stdout.find(FRAME_END)
    if end <= start:
        return None, "projection-frame-invalid"
    return stdout[start + len(FRAME_START):end].strip(), None


def run_ppux_projection_over_ssh(
    adapter: GcloudIapAdapter,
    request: PpuxProjectionRequest,
) -> dict[str, object]:
    """Run the fixed host command and record the framed structured payload."""
    try:
        completed = adapter._ssh(
            RESOURCE,
            ppux_projection_host_command(request),
            timeout=GCE_PPUX_PROJECTION_TRANSPORT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _failure(request, "projection-ssh-timeout")
    if completed.returncode != 0:
        return _ssh_failure(request, completed)
    framed, frame_error = _extract_framed_payload(completed.stdout)
    if frame_error is not None:
        return _failure(request, "projection-frame-invalid")
    try:
        payload = json.loads(framed)
    except json.JSONDecodeError:
        return _failure(request, "projection-evidence-not-json")
    if type(payload) is not dict:
        return _failure(request, "projection-evidence-malformed")
    try:
        return record_ppux_projection_result(payload, request)
    except PpuxProjectionRecorderError as error:
        return _failure(request, error.reason)


def execute_ppux_projection_transport(
    ingress: IssueCommentIngressResult,
    *,
    claims: Mapping[str, object],
    adapter: GcloudIapAdapter,
) -> dict[str, object]:
    """Policy-gated PPUX projection transport entry point.

    Accepts only the accepted-ppux-projection-envelope selector identity;
    returns the recorded evidence bundle under the ``ppux_projection`` key.
    """
    if ingress.status != "accepted" or ingress.reason != "accepted-ppux-projection-envelope":
        raise ValueError("ppux projection requires accepted canonical ingress evidence")
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot perform ppux projection")
    if ingress.handoff_id_or_none is not None:
        raise ValueError("ppux projection must not carry a handoff identity")
    if (
        ingress.issue_number is None
        or ingress.ppux_projection_branch_or_none is None
        or ingress.ppux_projection_sha_or_none is None
        or ingress.ppux_projection_input_ref_or_none is None
    ):
        raise ValueError("ppux projection ingress identity incomplete")
    request_material = "\0".join(
        [
            ingress.repository,
            str(ingress.issue_number),
            ingress.ppux_projection_branch_or_none,
            ingress.ppux_projection_sha_or_none,
            ingress.ppux_projection_input_ref_or_none,
        ]
    )
    request_suffix = hashlib.sha256(request_material.encode("ascii")).hexdigest()[:32]
    request = build_ppux_projection_request(
        repository=ingress.repository,
        issue_number=ingress.issue_number,
        branch=ingress.ppux_projection_branch_or_none,
        source_sha=ingress.ppux_projection_sha_or_none,
        input_ref=ingress.ppux_projection_input_ref_or_none,
        request_id=f"ppux-projection-{request_suffix}",
    )
    if not _policy().accepts(claims):
        return {"ppux_projection": _failure(request, "claims-rejected")}
    initial = adapter.observe_state(RESOURCE)
    start_issued = False
    if initial is VmState.STOPPED:
        if adapter.start(RESOURCE) is not True:
            return {"ppux_projection": _lifecycle_failure(request, "vm-start-failed", initial_state=initial)}
        start_issued = True
        if adapter.wait_until_running(RESOURCE) is not VmState.RUNNING:
            return {"ppux_projection": _lifecycle_failure(request, "vm-start-failed", initial_state=initial, start_issued=True)}
    elif initial is not VmState.RUNNING:
        return {"ppux_projection": _failure(request, "host-unavailable")}
    evidence = run_ppux_projection_over_ssh(adapter, request)
    evidence["vm_initial_state"] = initial.value
    evidence["start_issued"] = start_issued
    evidence["shutdown_issued"] = False
    return {"ppux_projection": evidence}


def _ingress_from_file(path: Path) -> IssueCommentIngressResult:
    """Reconstruct the ingress envelope from a persisted admission file.

    Every accepted selector identity survives reconstruction so a persisted
    envelope can reach the same transport the original trigger selected.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ingress payload must be an object")
    if raw.get("schema_version") != INGRESS_SCHEMA_VERSION:
        raise ValueError("ingress schema mismatch")
    return IssueCommentIngressResult(
        schema_version=INGRESS_SCHEMA_VERSION,
        status=raw.get("status"),
        reason=raw.get("reason"),
        repository=raw.get("repository"),
        issue_number=raw.get("issue_number"),
        comment_id=raw.get("comment_id"),
        actor=raw.get("actor"),
        handoff_id_or_none=raw.get("handoff_id_or_none"),
        logical_trigger_id_or_none=raw.get("logical_trigger_id_or_none"),
        run_attempt=raw.get("run_attempt") or 1,
        dev_validation_branch_or_none=raw.get("dev_validation_branch_or_none"),
        dev_validation_sha_or_none=raw.get("dev_validation_sha_or_none"),
        dev_validation_id_or_none=raw.get("dev_validation_id_or_none"),
        ppux_projection_branch_or_none=raw.get("ppux_projection_branch_or_none"),
        ppux_projection_sha_or_none=raw.get("ppux_projection_sha_or_none"),
        ppux_projection_input_ref_or_none=raw.get("ppux_projection_input_ref_or_none"),
        source_capsule_id_or_none=raw.get("source_capsule_id_or_none"),
        first_run_candidate_sha_or_none=raw.get("first_run_candidate_sha_or_none"),
        notion_read_request_id_or_none=raw.get("notion_read_request_id_or_none"),
        diagnostic_id_or_none=raw.get("diagnostic_id_or_none"),
        diagnostic_request_id_or_none=raw.get("diagnostic_request_id_or_none"),
        ruleset_prestate_sha256_or_none=raw.get("ruleset_prestate_sha256_or_none"),
    )


def _claims_from_file(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("claims payload must be an object")
    return dict(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fixed GCE PPUX prompt-projection transport")
    parser.add_argument("--ingress", required=True, type=Path)
    parser.add_argument("--claims", required=True, type=Path)
    args = parser.parse_args()
    ingress = _ingress_from_file(args.ingress)
    claims = _claims_from_file(args.claims)
    evidence = execute_ppux_projection_transport(
        ingress, claims=claims, adapter=GcloudIapAdapter()
    )
    print(json.dumps({"schema_version": "1.0", "evidence": evidence}))


if __name__ == "__main__":
    main()
