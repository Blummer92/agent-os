"""Build Docs batchUpdate requests that replace placeholder tokens with lesson content.

Pure function -- never touches a real file. Callers must duplicate the
template first (see drive_client.duplicate_template) and apply these
requests to the copy, never to the template itself. MVP scope is flat
paragraph placeholder replacement only -- no table or answer-key
templating.
"""
from __future__ import annotations

import re

from .content_spec import LessonContent
from .image_provenance import ImageProvenanceError, bind_caption_to_image


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


# #3389: student-visible provenance/AI-disclosure caption tokens.
#
# Each visual placement binding that carries governed provenance evidence
# renders its student-visible caption as a governed placeholder token,
# mirroring #3643's figure-label tokens: the governed Doc template carries
# ``{{provenance_caption_<role>_<slot>}}`` adjacent to the corresponding
# ``{{visual:<role>}}`` marker paragraph, and replaceAllText requests
# substitute the exact caption text at build time.
#
# Image-to-caption identity: the token name binds the same (role_id, slot_id)
# the visual marker binds, and the caption text is derived from the SAME
# binding's carried provenance through bind_caption_to_image (image_ref is
# the binding's asset identity). Attribution to the wrong image is
# impossible unless the (role, slot) identity itself is wrong -- and that
# fails closed in the placement path (resolve_exact_target requires exactly
# one marker match per binding).
#
# Fail-closed: bindings without carried provenance (the upstream path
# predates provenance tracking) emit no caption -- nothing is invented, and
# terminal QA stays silent about uncarried evidence per the documented #3389
# boundary. Malformed provenance, an untokenizable role/slot, or two
# bindings claiming the same caption token raise instead of guessing.
# Terminal QA verifies every emitted caption through the #3258 content
# contract: the token must be gone from the persisted artifact and the exact
# caption text must be present in it.

_CAPTION_TOKEN_PREFIX = "provenance_caption_"
_ROLE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_SLOT_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def provenance_caption_token(*, role_id: str, slot_id: str) -> str:
    """Build the caption placeholder token name for one (role_id, slot_id) binding."""
    role = role_id.strip() if isinstance(role_id, str) else ""
    slot = slot_id.strip() if isinstance(slot_id, str) else ""
    if not role or not _ROLE_TOKEN_RE.fullmatch(role):
        raise ImageProvenanceError(f"role_id {role_id!r} cannot be a caption token name")
    if not slot or not _SLOT_TOKEN_RE.fullmatch(slot):
        raise ImageProvenanceError(f"slot_id {slot_id!r} cannot be a caption token name")
    return f"{_CAPTION_TOKEN_PREFIX}{role}_{slot}"


def build_provenance_caption_requests(bindings) -> list[dict]:
    """Build replaceAllText requests rendering each carried provenance caption.

    One request per binding with non-None ``image_provenance``; the
    request shape matches ``build_docs_replace_requests`` so terminal QA
    derives the same governed content expectations from it.
    """
    requests: list[dict] = []
    seen: set[str] = set()
    for binding in bindings or ():
        provenance = getattr(binding, "image_provenance", None)
        if provenance is None:
            # Legacy/upstream predates provenance tracking: no caption is
            # invented for an unattributed image.
            continue
        token = provenance_caption_token(
            role_id=getattr(binding, "role_id", ""),
            slot_id=getattr(binding, "slot_id", ""),
        )
        if token in seen:
            raise ImageProvenanceError(
                f"duplicate provenance caption token {token}: "
                "refusing ambiguous image attribution"
            )
        seen.add(token)
        bound = bind_caption_to_image(
            image_ref=str(getattr(binding, "asset_id", "") or ""),
            provenance=provenance,
        )
        requests.append(
            {
                "replaceAllText": {
                    "containsText": {"text": "{{" + token + "}}", "matchCase": True},
                    "replaceText": bound["caption_text"],
                }
            }
        )
    return requests
