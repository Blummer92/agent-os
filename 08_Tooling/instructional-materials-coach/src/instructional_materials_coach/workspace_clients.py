"""Thin Slides/Docs batchUpdate wrappers.

Callers must pass the id of an already-duplicated copy, never the
template id -- batchUpdate mutates whatever file id it is given.
"""
from __future__ import annotations

from typing import Any


def build_slides_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build

    return build("slides", "v1", credentials=credentials)


def build_docs_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build

    return build("docs", "v1", credentials=credentials)


def apply_slides_requests(service: Any, presentation_id: str, requests: list[dict]) -> None:
    if not requests:
        return
    service.presentations().batchUpdate(
        presentationId=presentation_id, body={"requests": requests}
    ).execute()


def apply_docs_requests(service: Any, document_id: str, requests: list[dict]) -> None:
    if not requests:
        return
    service.documents().batchUpdate(
        documentId=document_id, body={"requests": requests}
    ).execute()
