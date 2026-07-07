"""Build Docs batchUpdate requests that replace placeholder tokens with lesson content.

Pure function -- never touches a real file. Callers must duplicate the
template first (see drive_client.duplicate_template) and apply these
requests to the copy, never to the template itself. MVP scope is flat
paragraph placeholder replacement only -- no table or answer-key
templating.
"""
from __future__ import annotations

from .content_spec import LessonContent


def build_docs_replace_requests(content: LessonContent) -> list[dict]:
    requests = []
    for token, value in content.placeholder_tokens().items():
        requests.append(
            {
                "replaceAllText": {
                    "containsText": {"text": "{{" + token + "}}", "matchCase": True},
                    "replaceText": value,
                }
            }
        )
    return requests
