"""Thin Drive API wrapper for governed template duplication and verification."""
from __future__ import annotations

import os
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
GOOGLE_DOCS_MIME = "application/vnd.google-apps.document"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"


def get_credentials(client_secret_path: str, token_path: str) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds: Credentials | None = None
    if token_path and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        if token_path:
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())
    return creds


def build_drive_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=credentials)


def get_file_metadata(service: Any, file_id: str) -> dict[str, Any]:
    return service.files().get(
        fileId=file_id,
        fields="id,name,mimeType,parents,trashed,capabilities(canCopy,canAddChildren),appProperties,webViewLink,driveId,"
        "md5Checksum,sha256Checksum,headRevisionId",
        supportsAllDrives=True,
    ).execute()


class DriveLookupError(RuntimeError):
    """A Drive file lookup that failed with a governed outcome.

    ``outcome`` is one of ``not-found`` (the file does not exist or was
    deleted), ``no-access`` (the caller cannot read it), or ``lookup-failed``
    (any other transport or API failure). Not-found and no-access are distinct:
    a deleted asset and a permission gap must never be conflated (#3256).
    """

    def __init__(self, file_id: str, outcome: str, detail: str = "") -> None:
        self.file_id = file_id
        self.outcome = outcome
        # Duck-typing hook: slot resolution and error classifiers read this
        # attribute to distinguish lookup outcomes without importing this module.
        self.drive_outcome = outcome
        self.detail = detail
        super().__init__(f"Drive lookup {outcome} for {file_id}{(': ' + detail) if detail else ''}")


def classify_drive_error(file_id: str, exc: BaseException) -> DriveLookupError:
    """Classify any Drive lookup exception into a governed outcome.

    Duck-types the googleapiclient ``HttpError`` (``exc.resp.status``) so this
    works without importing the client library: 404 -> ``not-found``,
    403 -> ``no-access``, anything else -> ``lookup-failed``. An exception that
    already carries a ``drive_outcome`` attribute keeps it.
    """
    outcome = getattr(exc, "drive_outcome", None)
    if outcome in ("not-found", "no-access", "lookup-failed"):
        return DriveLookupError(file_id, outcome, str(exc))
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status == 404:
        outcome = "not-found"
    elif status == 403:
        outcome = "no-access"
    else:
        outcome = "lookup-failed"
    return DriveLookupError(file_id, outcome, str(exc))


def describe_drive_file_outcome(service: Any, file_id: str) -> dict[str, Any]:
    """Describe a Drive file, returning a governed outcome envelope.

    Returns ``{"outcome": ..., "metadata": ...}`` where outcome is ``ok``,
    ``not-found``, ``no-access``, or ``lookup-failed``. Never raises for lookup
    failures; only for programming errors (unusable service). Prefer this over
    ``get_file_metadata`` when the caller must distinguish deletion from a
    permission gap.
    """
    try:
        metadata = get_file_metadata(service, file_id)
    except Exception as exc:  # noqa: BLE001 - classified below
        classified = classify_drive_error(file_id, exc)
        return {"outcome": classified.outcome, "metadata": None, "detail": classified.detail}
    return {"outcome": "ok", "metadata": metadata, "detail": ""}


def verify_template(service: Any, file_id: str, expected_mime: str) -> dict[str, Any]:
    meta = get_file_metadata(service, file_id)
    if meta.get("trashed"):
        raise RuntimeError(f"Template {file_id} is trashed")
    if meta.get("mimeType") != expected_mime:
        raise RuntimeError(f"Template {file_id} has unexpected MIME type")
    if meta.get("capabilities", {}).get("canCopy") is not True:
        raise RuntimeError(f"Template {file_id} cannot be copied")
    return meta


def verify_target_folder(service: Any, folder_id: str) -> dict[str, Any]:
    meta = get_file_metadata(service, folder_id)
    if meta.get("trashed"):
        raise RuntimeError(f"Target folder {folder_id} is trashed")
    if meta.get("mimeType") != GOOGLE_FOLDER_MIME:
        raise RuntimeError(f"Target {folder_id} is not a Drive folder")
    if meta.get("capabilities", {}).get("canAddChildren") is not True:
        raise RuntimeError(f"Target folder {folder_id} cannot accept children")
    return meta


def find_idempotent_copies(service: Any, target_folder_id: str, idempotency_key: str, role: str) -> list[dict[str, Any]]:
    safe_key = idempotency_key.replace("'", "\\'")
    safe_role = role.replace("'", "\\'")
    query = (
        f"'{target_folder_id}' in parents and trashed = false and "
        f"appProperties has {{ key='agent_os_idempotency_key' and value='{safe_key}' }} and "
        f"appProperties has {{ key='agent_os_artifact_role' and value='{safe_role}' }}"
    )
    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id,name,mimeType,parents,trashed,appProperties,webViewLink,driveId)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return list(result.get("files", []))


def duplicate_template(
    service: Any,
    template_id: str,
    target_folder_id: str,
    new_name: str,
    *,
    idempotency_key: str | None = None,
    role: str | None = None,
    input_fingerprint: str | None = None,
) -> Any:
    """Copy a template, stamping the idempotency key, role, and (#3252) the
    input fingerprint as Drive appProperties.

    ``input_fingerprint`` binds the consequential inputs to the created
    copy so recovery can reject a key reused with different inputs
    (``idempotency-key-input-mismatch``). It is secondary evidence only;
    the local resume record remains the primary continuation surface.
    """
    if not target_folder_id:
        raise ValueError("target_folder_id is required -- refusing to guess a destination.")

    if idempotency_key is None and role is None:
        result = service.files().copy(
            fileId=template_id,
            body={"name": new_name, "parents": [target_folder_id]},
            fields="id, webViewLink",
        ).execute()
        return result["id"]

    if not idempotency_key or not role:
        raise ValueError("idempotency_key and role must be supplied together")

    app_properties = {
        "agent_os_idempotency_key": idempotency_key,
        "agent_os_artifact_role": role,
    }
    if input_fingerprint:
        app_properties["agent_os_input_fingerprint"] = input_fingerprint
    body = {
        "name": new_name,
        "parents": [target_folder_id],
        "appProperties": app_properties,
    }
    return service.files().copy(
        fileId=template_id,
        body=body,
        fields="id,name,mimeType,parents,trashed,appProperties,webViewLink,driveId",
        supportsAllDrives=True,
    ).execute()


def verify_final_copy(
    service: Any,
    file_id: str,
    *,
    expected_mime: str,
    target_folder_id: str,
    idempotency_key: str,
    role: str,
) -> dict[str, Any]:
    meta = get_file_metadata(service, file_id)
    if meta.get("trashed") or meta.get("mimeType") != expected_mime:
        raise RuntimeError(f"Final {role} metadata is incompatible")
    if target_folder_id not in meta.get("parents", []):
        raise RuntimeError(f"Final {role} is outside the approved target folder")
    props = meta.get("appProperties", {})
    if props.get("agent_os_idempotency_key") != idempotency_key or props.get("agent_os_artifact_role") != role:
        raise RuntimeError(f"Final {role} idempotency evidence is missing or mismatched")
    return meta


def get_file_link(service: Any, file_id: str) -> str:
    return service.files().get(fileId=file_id, fields="webViewLink").execute()["webViewLink"]
