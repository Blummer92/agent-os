"""Thin Drive API wrapper: OAuth login and template duplication.

Exposes only file-copy (always creates a new file id) -- there is no
function here that can write to an existing file, so it is structurally
impossible for this module to edit a template in place.
"""
from __future__ import annotations

import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_credentials(client_secret_path: str, token_path: str) -> Credentials:
    """Load a cached OAuth token, refreshing or running the consent flow as needed."""
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


def build_drive_service(credentials: Credentials) -> Any:
    return build("drive", "v3", credentials=credentials)


def duplicate_template(service: Any, template_id: str, target_folder_id: str, new_name: str) -> str:
    """Duplicate template_id into target_folder_id. Never writes to template_id. Returns the new file's id."""
    if not target_folder_id:
        raise ValueError("target_folder_id is required -- refusing to guess a destination.")
    body = {"name": new_name, "parents": [target_folder_id]}
    created = service.files().copy(fileId=template_id, body=body, fields="id, webViewLink").execute()
    return created["id"]


def get_file_link(service: Any, file_id: str) -> str:
    file = service.files().get(fileId=file_id, fields="webViewLink").execute()
    return file["webViewLink"]
