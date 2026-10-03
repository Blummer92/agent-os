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


def _validate_replace_results(
    requests: list[dict],
    response: Any,
    *,
    surface: str,
    content_fetcher: Any = None,
) -> None:
    """Validate per-request replaceAllText outcomes.

    ``content_fetcher`` is the #3252 idempotency safety net: when supplied
    (retry path only, never the hot path) and a request reports
    ``occurrencesChanged == 0``, the current document text is read back. If
    the replacement text is already present, the request is treated as
    already-applied instead of failing with "required placeholder was not
    replaced". If the text is genuinely absent — or unreadable — the
    failure stands. A fetcher that raises is treated as unreadable.
    """
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
            if content_fetcher is not None and _already_applied(content_fetcher, replace):
                continue
            raise RuntimeError(f"{surface} required placeholder was not replaced: request={index}; token={token!r}")


def _already_applied(content_fetcher: Any, replace: Any) -> bool:
    """True when the replacement text is already present in the document."""
    try:
        text = content_fetcher()
    except Exception:
        return False
    if not isinstance(text, str) or not text:
        return False
    new_text = replace.get("replaceText", {}) if isinstance(replace, dict) else {}
    replacement = new_text.get("text", "") if isinstance(new_text, dict) else ""
    return isinstance(replacement, str) and bool(replacement) and replacement in text


def apply_slides_requests(
    service: Any,
    presentation_id: str,
    requests: list[dict],
    *,
    required_revision_id: str | None = None,
    content_fetcher: Any = None,
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
    _validate_replace_results(requests, response, surface="Slides", content_fetcher=content_fetcher)


def apply_docs_requests(
    service: Any,
    document_id: str,
    requests: list[dict],
    *,
    required_revision_id: str | None = None,
    content_fetcher: Any = None,
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
    _validate_replace_results(requests, response, surface="Docs", content_fetcher=content_fetcher)
