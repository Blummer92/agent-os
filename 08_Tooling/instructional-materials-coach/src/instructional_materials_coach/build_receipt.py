"""Versioned, non-authorizing evidence record for one canonical IMC build.

#3454 / #3259 D4. No Google access or lesson-content copying happens here.
"""
from __future__ import annotations

import json
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping

from .drive_client import GOOGLE_DOCS_MIME, GOOGLE_SLIDES_MIME
from .live_build import LiveBuildInput, LiveBuildReceipt, evaluate_artifact_completeness

BUILD_RECEIPT_CONTRACT = "imc-build-receipt-v1"
_REQUIREMENT_FIELDS = ("requirement_id", "contract_version", "record_revision", "source_fingerprint")


def _package_version() -> str | None:
    try:
        return version("instructional-materials-coach")
    except PackageNotFoundError:
        return None


def _artifact_record(build: LiveBuildInput | None, receipt: LiveBuildReceipt | None, role: str) -> dict[str, Any]:
    artifact = getattr(receipt, role, None) if receipt is not None else None
    qa = getattr(getattr(receipt, "terminal_qa", None), role, None)
    requested_mime = GOOGLE_SLIDES_MIME if role == "slides" else GOOGLE_DOCS_MIME
    if artifact is None:
        return {
            "role": role, "file_id": None, "revision_id": None, "state": "not-run",
            "delivery_kind": None, "terminal_qa_state": "not-run",
            "requested_format": {"status": "blocked-production", "complete": False, "reason_code": "no-artifact-receipt"},
        }
    completeness = (
        evaluate_artifact_completeness(
            artifact, requested_mime_type=requested_mime, target_folder_id=build.target_folder_id,
        )
        if build is not None
        else None
    )
    return {
        "role": role,
        "file_id": artifact.file_id or None,
        "revision_id": getattr(qa, "revision_id", None) or None,
        "state": artifact.state,
        "delivery_kind": artifact.delivery_kind,
        "terminal_qa_state": artifact.terminal_qa_state,
        "requested_format": (
            {"status": completeness.status, "complete": completeness.complete,
             "reason_code": completeness.reason_code}
            if completeness is not None else
            {"status": "blocked-production", "complete": False, "reason_code": "build-input-unavailable"}
        ),
    }


def build_receipt_record(
    build: LiveBuildInput | None,
    receipt: LiveBuildReceipt | None,
    *,
    requirement_identity: Mapping[str, object] | None = None,
    template_revisions: Mapping[str, object] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Produce deterministic, JSON-safe evidence; never infer missing identities.

    The Scheduler host and CLI supply the same exact governed identity and
    template-revision inputs. None of these fields confer approval or authority.
    """
    identity = requirement_identity or {}
    templates = template_revisions or {}
    requirement = {
        key: identity.get(key) if isinstance(identity.get(key), str) else None
        for key in _REQUIREMENT_FIELDS
    }
    expectation = getattr(build, "qa_expectations", None)
    qa = getattr(receipt, "terminal_qa", None)
    placements = sorted(
        (
            {"role_id": b.role_id, "slot_id": b.slot_id, "asset_id": b.asset_id,
             "idempotency_key": build.idempotency_key}
            for b in getattr(build, "visual_placements", ()) or ()
        ),
        key=lambda item: (item["role_id"], item["slot_id"], item["asset_id"]),
    ) if build is not None else []
    return {
        "contract_version": BUILD_RECEIPT_CONTRACT,
        "idempotency_key": build.idempotency_key if build is not None else None,
        "requirement_identity": requirement,
        "templates": {
            "slides": {"file_id": build.slides_template_id if build is not None else None,
                       "revision_id": templates.get("slides") if isinstance(templates.get("slides"), str) else None},
            "worksheet": {"file_id": build.doc_template_id if build is not None else None,
                          "revision_id": templates.get("worksheet") if isinstance(templates.get("worksheet"), str) else None},
        },
        "artifacts": {
            role: _artifact_record(build, receipt, role) for role in ("slides", "worksheet")
        },
        "qa_expectations_hash": expectation.expectations_hash() if expectation is not None else None,
        "terminal_qa_state": getattr(qa, "state", None),
        "placement_receipt_references": placements,
        "renderer_version": _package_version(),
        "succeeded": bool(receipt.succeeded) if receipt is not None else False,
        "failure_code": error_code if type(error_code) is str else None,
        "authority": {
            "execution_authorized": False,
            "production_authorized": False,
            "classroom_ready": False,
        },
    }


def write_build_receipt_atomic(path: str | Path, record: Mapping[str, Any]) -> None:
    """Opt-in local receipt persistence, atomic even if serialization fails."""
    target = Path(path)
    if not str(path):
        raise ValueError("receipt path must not be empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
