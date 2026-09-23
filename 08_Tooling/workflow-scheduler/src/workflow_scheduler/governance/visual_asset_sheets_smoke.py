"""Governed read-only Sheets smoke capability for Visual Asset Sync (#1926).

This module is deliberately non-authorizing.  It binds one bounded Sheets read
request to repository/issue/source identity, verifies the effective OAuth grant
before the API call, and emits sanitized evidence only.  Credential material is
supplied by an external governed injector and is never serialized by this module.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Literal, Mapping, Sequence

REPOSITORY = "Blummer92/agent-os"
CONSUMER_ISSUE = 734
REQUIRED_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
API_METHOD = "spreadsheets.values.get"
MAX_ROWS = 455
_SHA40 = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SPREADSHEET_ID = re.compile(r"^[A-Za-z0-9_-]{20,160}$", re.ASCII)
_A1 = re.compile(r"^'[^'\r\n]{1,120}'![A-Z]{1,3}[1-9][0-9]{0,5}:[A-Z]{1,3}[1-9][0-9]{0,5}$", re.ASCII)


@dataclass(frozen=True, slots=True, kw_only=True)
class SheetsSmokeRequest:
    repository: str
    issue_number: int
    source_sha: str
    spreadsheet_id: str
    worksheet_name: str
    a1_range: str
    request_id: str
    execution_authorized: Literal[False] = field(default=False, init=False)
    external_write_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "repository": self.repository,
            "issue_number": self.issue_number,
            "source_sha": self.source_sha,
            "spreadsheet_id": self.spreadsheet_id,
            "worksheet_name": self.worksheet_name,
            "a1_range": self.a1_range,
            "request_id": self.request_id,
            "execution_authorized": False,
            "external_write_authorized": False,
        }


def build_request(*, repository: object, issue_number: object, source_sha: object,
                  spreadsheet_id: object, worksheet_name: object,
                  a1_range: object) -> SheetsSmokeRequest:
    if repository != REPOSITORY:
        raise ValueError("non-canonical repository rejected")
    if issue_number != CONSUMER_ISSUE:
        raise ValueError("non-canonical consumer issue rejected")
    if type(source_sha) is not str or _SHA40.fullmatch(source_sha) is None:
        raise ValueError("invalid source sha")
    if type(spreadsheet_id) is not str or _SPREADSHEET_ID.fullmatch(spreadsheet_id) is None:
        raise ValueError("invalid spreadsheet id")
    if type(worksheet_name) is not str or not worksheet_name or len(worksheet_name) > 120:
        raise ValueError("invalid worksheet name")
    if "'" in worksheet_name or "\n" in worksheet_name or "\r" in worksheet_name:
        raise ValueError("unsafe worksheet name")
    expected_prefix = f"'{worksheet_name}'!"
    if type(a1_range) is not str or _A1.fullmatch(a1_range) is None or not a1_range.startswith(expected_prefix):
        raise ValueError("invalid bounded a1 range")
    material = json.dumps(
        [repository, issue_number, source_sha, spreadsheet_id, worksheet_name, a1_range, REQUIRED_SCOPE, API_METHOD],
        separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")
    request_id = "sheets-smoke:" + hashlib.sha256(b"agent-os-sheets-smoke:v1\0" + material).hexdigest()
    return SheetsSmokeRequest(
        repository=repository,
        issue_number=issue_number,
        source_sha=source_sha,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
        a1_range=a1_range,
        request_id=request_id,
    )


def verify_request(request: object) -> SheetsSmokeRequest:
    if type(request) is not SheetsSmokeRequest:
        raise TypeError("request must be exact SheetsSmokeRequest")
    expected = build_request(
        repository=request.repository,
        issue_number=request.issue_number,
        source_sha=request.source_sha,
        spreadsheet_id=request.spreadsheet_id,
        worksheet_name=request.worksheet_name,
        a1_range=request.a1_range,
    )
    if expected.request_id != request.request_id:
        raise ValueError("sheets smoke request identity drift")
    return request


def _scope_set(value: object) -> frozenset[str]:
    if type(value) is str:
        items = value.split()
    elif type(value) in {list, tuple}:
        items = list(value)
    else:
        raise ValueError("oauth scope evidence unavailable")
    if not items or any(type(item) is not str or not item for item in items):
        raise ValueError("oauth scope evidence unavailable")
    return frozenset(items)


def _base(request: SheetsSmokeRequest, *, status: str, reason: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "status": status,
        "reason_codes": [reason],
        "repository": request.repository,
        "issue_number": request.issue_number,
        "source_sha": request.source_sha,
        "request_id": request.request_id,
        "api_method": API_METHOD,
        "spreadsheet_id": request.spreadsheet_id,
        "a1_range": request.a1_range,
        "required_scope": REQUIRED_SCOPE,
        "scope_verified": False,
        "response_row_count": 0,
        "cleanup_complete": True,
        "external_write_performed": False,
        "sheet_write_performed": False,
        "drive_access_performed": False,
        "notion_access_performed": False,
        "execution_authorized": False,
        "production_authorized": False,
        "credential_material_emitted": False,
    }


def execute_smoke(
    request: SheetsSmokeRequest,
    *,
    inspect_effective_scopes: Callable[[], object],
    values_get: Callable[[str, str], Mapping[str, object]],
) -> dict[str, object]:
    """Execute one read after exact effective-scope verification.

    The callables are injected by the governed runtime so offline tests can prove
    ordering and fail-closed behavior without credentials or network access.
    """
    request = verify_request(request)
    evidence = _base(request, status="blocked", reason="scope-unverified")
    try:
        scopes = _scope_set(inspect_effective_scopes())
    except Exception:
        evidence["reason_codes"] = ["scope-unverifiable"]
        return evidence
    if scopes != frozenset({REQUIRED_SCOPE}):
        evidence["reason_codes"] = ["scope-not-least-privilege"]
        return evidence
    evidence["scope_verified"] = True
    response = values_get(request.spreadsheet_id, request.a1_range)
    if type(response) is not dict:
        evidence["reason_codes"] = ["sheets-response-malformed"]
        return evidence
    values = response.get("values", [])
    if type(values) is not list or len(values) > MAX_ROWS or any(type(row) is not list for row in values):
        evidence["reason_codes"] = ["sheets-response-malformed"]
        return evidence
    evidence.update(
        status="success",
        reason_codes=["bounded-read-complete"],
        response_row_count=len(values),
    )
    return evidence


__all__ = [
    "API_METHOD", "CONSUMER_ISSUE", "MAX_ROWS", "REPOSITORY", "REQUIRED_SCOPE",
    "SheetsSmokeRequest", "build_request", "execute_smoke", "verify_request",
]
