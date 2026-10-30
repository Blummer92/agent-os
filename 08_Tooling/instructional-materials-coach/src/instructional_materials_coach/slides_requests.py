"""Build Slides batchUpdate requests that replace placeholder tokens with lesson content.

Pure function -- never touches a real file. Callers must duplicate the
template first (see drive_client.duplicate_template) and apply these
requests to the copy, never to the template itself.
"""
from __future__ import annotations

from .content_spec import LessonContent

# QA-only request metadata: the authored 1-based slide["index"] for
# slide-scoped replace requests. Terminal QA binds content expectations to
# this governed slide identity; the Slides API never sees the key --
# workspace_clients.apply_slides_requests strips it before batchUpdate.
QA_SLIDE_INDEX_KEY = "qa_slide_index"


def build_slides_replace_requests(content: LessonContent) -> list[dict]:
    slide_indexes = content.slide_token_indexes()
    requests = []
    for token, value in content.placeholder_tokens().items():
        request: dict = {
            "replaceAllText": {
                "containsText": {"text": "{{" + token + "}}", "matchCase": True},
                "replaceText": value,
            }
        }
        slide_index = slide_indexes.get(token)
        if slide_index is not None:
            request[QA_SLIDE_INDEX_KEY] = slide_index
        requests.append(request)
    return requests
