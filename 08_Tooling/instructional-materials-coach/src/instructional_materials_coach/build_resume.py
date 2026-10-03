"""Build resume records for retry continuation (#3252).

A resume record is a JSON file under ``reports/build-resume/`` keyed by
idempotency key. It records per-role state (``planned``/``created``/
``updated``/``failed``), the recovered file IDs, and the indices of the
replace requests already applied. On retry, ``build_live_materials``
loads the record and skips already-applied work instead of re-applying
blindly — the fix for the permanent "required placeholder was not
replaced" failure.

The record is written after every state transition (crash-safe: it always
describes the last completed step). It never causes a second copy:
recovery always goes through ``find_idempotent_copies`` first.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Mapping

DEFAULT_BUILD_RESUME_DIR = "reports/build-resume"
BUILD_RESUME_CONTRACT_ID = "build-resume-v1"


class ResumeRecordInvalidError(RuntimeError):
    pass


_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ROLE_STATES = ("planned", "created", "updated", "failed")


def _utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def resume_path(resume_dir: str | Path, idempotency_key: str) -> Path:
    if not _KEY_RE.fullmatch(idempotency_key or ""):
        raise ValueError("idempotency_key must be a filename-safe non-empty string")
    return Path(resume_dir) / f"{idempotency_key}.json"


def new_resume_record(idempotency_key: str, input_fingerprint: str = "") -> dict[str, Any]:
    """Create the initial in-memory resume record for a build run."""
    if not _KEY_RE.fullmatch(idempotency_key or ""):
        raise ValueError("idempotency_key must be a filename-safe non-empty string")

    def _role_state() -> dict[str, Any]:
        return {
            "state": "planned",
            "file_id": "",
            "applied_request_indices": [],
            "error": "",
        }

    return {
        "contract_id": BUILD_RESUME_CONTRACT_ID,
        "idempotency_key": idempotency_key,
        "input_fingerprint": input_fingerprint or "",
        "slides": _role_state(),
        "worksheet": _role_state(),
        "updated_at": _utc_now(),
    }


def load_resume_record(
    resume_dir: str | Path, idempotency_key: str
) -> dict[str, Any] | None:
    """Load persisted resume state; malformed existing state fails closed."""
    path = resume_path(resume_dir, idempotency_key)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResumeRecordInvalidError("resume-record-invalid: unreadable persisted state") from exc
    if not isinstance(raw, dict):
        raise ResumeRecordInvalidError("resume-record-invalid: record must be a mapping")
    if raw.get("contract_id") != BUILD_RESUME_CONTRACT_ID:
        raise ResumeRecordInvalidError("resume-record-invalid: contract mismatch")
    if raw.get("idempotency_key") != idempotency_key:
        raise ResumeRecordInvalidError("resume-record-invalid: idempotency key mismatch")
    for role in ("slides", "worksheet"):
        state = raw.get(role)
        if not isinstance(state, dict) or state.get("state") not in _ROLE_STATES:
            raise ResumeRecordInvalidError(f"resume-record-invalid: {role} state is invalid")
        indices = state.get("applied_request_indices")
        if not isinstance(indices, list) or any(
            type(index) is not int or index < 0 for index in indices
        ):
            raise ResumeRecordInvalidError(
                f"resume-record-invalid: {role} applied_request_indices are invalid"
            )
    return raw


def write_resume_record(resume_dir: str | Path, record: Mapping[str, Any]) -> Path:
    """Persist the resume record, stamping ``updated_at``. Returns the path."""
    key = record.get("idempotency_key")
    path = resume_path(resume_dir, str(key))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload["updated_at"] = _utc_now()
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def mark_role_state(
    record: dict[str, Any],
    role: str,
    *,
    state: str,
    file_id: str = "",
    error: str = "",
) -> None:
    """Update one role's state in an in-memory record (then persist)."""
    if role not in ("slides", "worksheet"):
        raise ValueError(f"unknown resume role: {role!r}")
    if state not in _ROLE_STATES:
        raise ValueError(f"unknown resume state: {state!r}")
    entry = record[role]
    entry["state"] = state
    if file_id:
        entry["file_id"] = file_id
    entry["error"] = error
