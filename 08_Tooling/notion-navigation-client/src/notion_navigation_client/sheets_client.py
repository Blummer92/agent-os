"""Thin Sheets API wrapper: OAuth login and one read call.

Scoped to `spreadsheets.readonly` and exposes only `fetch_tab_values` --
there is no update/append/batchUpdate call anywhere in this module, so it
is structurally impossible for this client to write to the sheet.
"""
from __future__ import annotations

import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


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


def build_sheets_service(credentials: Credentials) -> Any:
    return build("sheets", "v4", credentials=credentials)


def fetch_tab_values(service: Any, spreadsheet_id: str, tab_name: str) -> list[list[str]]:
    """Return the raw header + data rows for one tab. Read-only; never writes."""
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=tab_name)
        .execute()
    )
    return result.get("values", [])
