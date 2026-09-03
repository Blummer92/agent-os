"""Thin Slides/Docs wrappers with revision-bound writes."""
from __future__ import annotations
from typing import Any


def build_slides_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build
    return build("slides", "v1", credentials=credentials)


def build_docs_service(credentials: Any) -> Any:
    from googleapiclient.discovery import build
    return build("docs", "v1", credentials=credentials)


def get_slides_revision_id(service: Any, presentation_id: str) -> str:
    revision = service.presentations().get(presentationId=presentation_id, fields="revisionId").execute().get("revisionId")
    if not revision:
        raise RuntimeError("Slides revisionId is required before mutation")
    return revision


def get_docs_revision_id(service: Any, document_id: str) -> str:
    revision = service.documents().get(documentId=document_id, fields="revisionId").execute().get("revisionId")
    if not revision:
        raise RuntimeError("Docs revisionId is required before mutation")
    return revision


def _validate_replace_results(requests: list[dict], response: Any, *, surface: str) -> None:
    replies = response.get("replies", []) if isinstance(response, dict) else []
    if len(replies) != len(requests):
        raise RuntimeError(f"{surface} batchUpdate did not return one result per request")
    for index, (request, reply) in enumerate(zip(requests, replies), start=1):
        replace = request.get("replaceAllText") if isinstance(request, dict) else None
        if replace is None:
            continue
        result = reply.get("replaceAllText", {}) if isinstance(reply, dict) else {}
        changed = result.get("occurrencesChanged")
        if not isinstance(changed, int) or isinstance(changed, bool) or changed < 1:
            contains = replace.get("containsText", {}) if isinstance(replace, dict) else {}
            token = contains.get("text", "") if isinstance(contains, dict) else ""
            raise RuntimeError(f"{surface} required placeholder was not replaced: request={index}; token={token!r}")


def apply_slides_requests(
    service: Any,
    presentation_id: str,
    requests: list[dict],
    *,
    required_revision_id: str | None = None,
) -> None:
    if not requests:
        return
    body: dict[str, Any] = {"requests": requests}
    if required_revision_id is not None:
        body["writeControl"] = {"requiredRevisionId": required_revision_id}
    response = service.presentations().batchUpdate(
        presentationId=presentation_id,
        body=body,
    ).execute()
    _validate_replace_results(requests, response, surface="Slides")


def apply_docs_requests(
    service: Any,
    document_id: str,
    requests: list[dict],
    *,
    required_revision_id: str | None = None,
) -> None:
    if not requests:
        return
    body: dict[str, Any] = {"requests": requests}
    if required_revision_id is not None:
        body["writeControl"] = {"requiredRevisionId": required_revision_id}
    response = service.documents().batchUpdate(
        documentId=document_id,
        body=body,
    ).execute()
    _validate_replace_results(requests, response, surface="Docs")
