"""Pure-local validation for the Instructional Materials Coach v1 dry-run contract."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from workflow_scheduler.models import ExecutionContext, ExecutionRequest

CONTRACT_VERSION = "imc-materials-task-v1"
OPERATION = "build_materials_bundle"
OWNER = "instructional-materials-coach"
SUCCESS_MESSAGE = "Instructional Materials Coach command plan validated; no execution performed."
FAILURE_MESSAGE = "Instructional Materials Coach contract validation failed."
BLOCKED_MESSAGE = "Instructional Materials Coach dry-run request is not authorized."
MAX_RECEIPT_BYTES = 8192

_PAYLOAD_KEYS = {
    "contract_version",
    "operation",
    "dry_run",
    "execution_authorized",
    "content_path",
    "slides_template_id",
    "doc_template_id",
    "target_drive_folder_id",
    "lessons_dir",
    "production_gates",
    "governed_field_risk",
    "writes_governed_field",
}
_GATE_KEYS = {
    "source_confidence",
    "unit_readiness",
    "modeling_readiness",
    "evidence_target",
    "blockers",
}
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._:-]+\Z")
_PATH_RE = re.compile(r"[A-Za-z0-9._/ -]+\Z")
_DANGEROUS = ("$(", "${", "`", ";", "&&", "||", "<", ">", "\r", "\n", "\x00")


def _failure() -> dict[str, Any]:
    return {"status": "failure", "message": FAILURE_MESSAGE}


def _blocked(reason: str) -> dict[str, Any]:
    return {"status": "blocked", "message": BLOCKED_MESSAGE, "blocked_reason": reason}


def _exact_string(value: object, *, maximum: int, allow_blank: bool = False) -> bool:
    if type(value) is not str:
        return False
    if not value or len(value) > maximum:
        return bool(allow_blank and value == "")
    return value.isprintable() and not any(token in value for token in _DANGEROUS)


def _relative_path(value: object) -> bool:
    if not _exact_string(value, maximum=256) or value.startswith("-"):
        return False
    assert type(value) is str
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value) or "\\" in value:
        return False
    if not _PATH_RE.fullmatch(value):
        return False
    return all(part != ".." for part in value.split("/"))


def _safe_token(value: object) -> bool:
    return (
        _exact_string(value, maximum=256)
        and not value.startswith("-")
        and bool(_SAFE_TOKEN_RE.fullmatch(value))
    )


def _valid_request_shell(request: object) -> bool:
    if type(request) is not ExecutionRequest:
        return False
    if type(request.execution_context) is not ExecutionContext:
        return False
    if not _exact_string(request.task_id, maximum=128):
        return False
    if not _exact_string(request.workflow_id, maximum=128):
        return False
    if not _exact_string(request.owner, maximum=128):
        return False
    if not _exact_string(request.idempotency_key, maximum=256):
        return False
    if not _exact_string(request.mode, maximum=128):
        return False
    if type(request.approval_required) is not bool or type(request.production_ready) is not bool:
        return False
    if type(request.execution_id) is not str or not _exact_string(request.execution_id, maximum=128):
        return False
    if type(request.run_id) is not str or not _exact_string(request.run_id, maximum=128):
        return False
    if type(request.attempt_number) is not int or request.attempt_number < 0:
        return False
    if type(request.created_at) is not datetime:
        return False
    if request.batch_id is not None and not _exact_string(request.batch_id, maximum=128):
        return False
    return True


def _has_exact_keys(value: object, expected: set[str]) -> bool:
    if type(value) is not dict:
        return False
    keys = tuple(value.keys())
    if any(type(key) is not str for key in keys):
        return False
    return len(keys) == len(expected) and set(keys) == expected


def validate_instructional_materials_contract(request: ExecutionRequest) -> dict[str, Any]:
    """Validate one C2 v1 dry-run request and render a bounded inert receipt."""
    if not _valid_request_shell(request):
        return _failure()

    payload = request.payload
    if not _has_exact_keys(payload, _PAYLOAD_KEYS):
        return _failure()

    if not _exact_string(payload["contract_version"], maximum=128):
        return _failure()
    if payload["contract_version"] != CONTRACT_VERSION:
        return _failure()
    if not _exact_string(payload["operation"], maximum=128):
        return _failure()
    if payload["operation"] != OPERATION:
        return _failure()
    if type(payload["dry_run"]) is not bool or type(payload["execution_authorized"]) is not bool:
        return _failure()
    if type(payload["governed_field_risk"]) is not bool or type(payload["writes_governed_field"]) is not bool:
        return _failure()
    if not _relative_path(payload["content_path"]) or not _relative_path(payload["lessons_dir"]):
        return _failure()
    if not _safe_token(payload["slides_template_id"]):
        return _failure()
    if not _safe_token(payload["doc_template_id"]):
        return _failure()
    if not _safe_token(payload["target_drive_folder_id"]):
        return _failure()

    gates = payload["production_gates"]
    if not _has_exact_keys(gates, _GATE_KEYS):
        return _failure()
    for key in ("source_confidence", "unit_readiness", "modeling_readiness", "blockers"):
        if not _exact_string(gates[key], maximum=128):
            return _failure()
    if not _exact_string(gates["evidence_target"], maximum=512):
        return _failure()

    if request.owner != OWNER:
        return _failure()
    if request.mode != "Draft":
        return _blocked("production-mode-not-authorized")
    if request.approval_required:
        return _blocked("approval-path-not-authorized")
    if request.production_ready:
        return _blocked("production-mode-not-authorized")
    if request.batch_id is not None:
        return _blocked("batching-not-authorized")
    if not payload["dry_run"] or payload["execution_authorized"]:
        return _blocked("live-execution-not-authorized")
    if payload["governed_field_risk"] or payload["writes_governed_field"]:
        return _blocked("governed-field-risk")
    if (
        gates["source_confidence"] != "approved"
        or gates["unit_readiness"] != "ready"
        or gates["modeling_readiness"] != "ready_for_slides"
        or gates["blockers"] != "none"
    ):
        return _blocked("production-gate-not-satisfied")

    result = {
        "status": "success",
        "message": SUCCESS_MESSAGE,
        "output": {
            "contract_version": CONTRACT_VERSION,
            "operation": OPERATION,
            "entry_point": "instructional_materials_coach.cli:main",
            "command": [
                "imc-build",
                "build",
                "--content",
                payload["content_path"],
                "--slides-template",
                payload["slides_template_id"],
                "--doc-template",
                payload["doc_template_id"],
                "--target-folder",
                payload["target_drive_folder_id"],
                "--lessons-dir",
                payload["lessons_dir"],
            ],
            "dry_run": True,
            "execution_authorized": False,
            "authority": {
                "approval": False,
                "execution": False,
                "external_write": False,
                "freshness": False,
                "capability": False,
            },
            "external_calls": [],
            "files_created": [],
            "credentials_accessed": False,
            "allow_write_enabled": False,
        },
    }
    if len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")) > MAX_RECEIPT_BYTES:
        return _failure()
    return result
