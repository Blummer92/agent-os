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
        fields="id,name,mimeType,parents,trashed,capabilities(canCopy,canAddChildren),appProperties,webViewLink,driveId",
        supportsAllDrives=True,
    ).execute()


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
) -> Any:
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

    body = {
        "name": new_name,
        "parents": [target_folder_id],
        "appProperties": {
            "agent_os_idempotency_key": idempotency_key,
            "agent_os_artifact_role": role,
        },
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
