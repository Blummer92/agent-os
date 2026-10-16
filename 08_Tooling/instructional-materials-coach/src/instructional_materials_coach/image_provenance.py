"""Student-visible image provenance and AI disclosure (#3389).

Every student-facing instructional image must disclose where it came from
at the point of use: a real/web photograph shows the photographer/creator
name adjacent to the image; an AI-generated image is explicitly labeled as
AI-generated; an unknown/ambiguous origin is labeled "source unknown" and
routes to manual review rather than being silently presented as ordinary
sourced photography.

This module is the repo-side mechanism: pure provenance evidence
validation plus the student-visible caption builder. The caption text it
produces is what composition surfaces (direct DOCX authoring, future
builders) render adjacent to the image so the label travels with the
visual through export/reflow.

Origin vocabulary (deliberately small; never inferred):

- ``human-photograph``: a real photograph by a human creator. Verified
  for terminal QA only when a creator name is known.
- ``ai-generated``: an AI-generated image. Always labeled "AI-generated
  image" at the point of use.
- ``unknown``: origin ambiguous or unavailable. Student-visible label
  says "Image source unknown" (fail-closed disclosure, never silent
  omission); terminal QA reports an explicit unresolved-provenance state.

Provenance is explicit governed input carried on the plan assignment
(`image_provenance`); it is never invented here. A missing provenance
mapping means the upstream path predates provenance tracking (None); a
malformed mapping is an upstream contract breach and fails closed.

Pure repository-side validation; no services, no credentials, no image
metadata lookups (web-photo provenance needs live image metadata --
documented validation gap, Phase 1 partial-dependency classification).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: Governed origin vocabulary. Nothing outside this set is ever accepted;
#: anything else is malformed evidence, not a new kind.
ORIGIN_KINDS = frozenset({"human-photograph", "ai-generated", "unknown"})

#: Student-visible label for AI-generated imagery (issue #3389 teacher
#: requirement: "If it's an AI photo it should say it's AI").
AI_GENERATED_LABEL = "AI-generated image"

#: Student-visible label when the origin cannot be established
#: (fail-closed disclosure rather than silent omission).
UNKNOWN_ORIGIN_LABEL = "Image source unknown"

#: Student-visible label when a human photograph's creator is not known.
UNKNOWN_CREATOR_LABEL = "Photo: source unknown"


class ImageProvenanceError(ValueError):
    """Governed image-provenance evidence is malformed."""


@dataclass(frozen=True)
class ImageProvenance:
    """Provenance evidence for one student-facing instructional image."""

    origin_kind: str
    creator_name: str | None = None
    source_detail: str | None = None

    def __post_init__(self) -> None:
        if self.origin_kind not in ORIGIN_KINDS:
            raise ImageProvenanceError(
                f"origin_kind must be one of {sorted(ORIGIN_KINDS)}"
            )
        for name, value in (("creator_name", self.creator_name),
                            ("source_detail", self.source_detail)):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ImageProvenanceError(f"{name} must be non-empty text when supplied")

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_kind": self.origin_kind,
            "creator_name": self.creator_name,
            "source_detail": self.source_detail,
        }


def image_provenance_from_mapping(value: Mapping[str, Any] | None) -> ImageProvenance | None:
    """Validate governed provenance evidence, or fail closed.

    ``None`` means the upstream path carries no provenance evidence
    (predates provenance tracking) -- never invented here. A non-mapping
    or a mapping with an invalid origin kind is an upstream contract
    breach and raises. A well-formed ``unknown`` mapping is explicit,
    carried evidence: it discloses "source unknown" and routes to manual
    review downstream.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ImageProvenanceError("image_provenance must be a mapping when supplied")
    try:
        origin_kind = value["origin_kind"]
        creator_name = value.get("creator_name")
        source_detail = value.get("source_detail")
    except (KeyError, AttributeError) as exc:
        raise ImageProvenanceError(f"image_provenance is missing required fields: {exc}") from exc
    return ImageProvenance(
        origin_kind=origin_kind, creator_name=creator_name, source_detail=source_detail
    )


def student_visible_caption(provenance: ImageProvenance) -> str:
    """Build the student-visible provenance/AI-disclosure caption text.

    - AI-generated image -> "AI-generated image".
    - Human photograph with known creator -> "Photo: <creator name>".
    - Human photograph with unknown creator -> "Photo: source unknown"
      (explicit disclosure, never silent omission).
    - Unknown origin -> "Image source unknown".
    """
    if not isinstance(provenance, ImageProvenance):
        raise ImageProvenanceError("provenance must be an ImageProvenance")
    if provenance.origin_kind == "ai-generated":
        return AI_GENERATED_LABEL
    if provenance.origin_kind == "human-photograph":
        if provenance.creator_name:
            return f"Photo: {provenance.creator_name.strip()}"
        return UNKNOWN_CREATOR_LABEL
    return UNKNOWN_ORIGIN_LABEL


def provenance_qa_outcome(provenance: ImageProvenance) -> str:
    """Terminal-QA outcome for carried provenance evidence.

    Returns ``"verified"`` only when the origin is positively established:
    an AI-generated image (explicitly disclosed), or a human photograph
    with a known creator name. ``"unresolved"`` covers unknown origin and
    human photographs with no known creator -- both route to manual review
    with the role named; neither may be silently presented as ordinary
    sourced photography.
    """
    if not isinstance(provenance, ImageProvenance):
        raise ImageProvenanceError("provenance must be an ImageProvenance")
    if provenance.origin_kind == "ai-generated":
        return "verified"
    if provenance.origin_kind == "human-photograph" and provenance.creator_name:
        return "verified"
    return "unresolved"


def bind_caption_to_image(
    *,
    image_ref: str,
    provenance: ImageProvenance,
    caption_text: str | None = None,
) -> dict[str, Any]:
    """Bind a provenance caption to its image so the label travels with it.

    Returns the bound structure composition surfaces render: the image
    reference, the exact student-visible caption text, and the provenance
    evidence it was derived from. Rendering the caption from this binding
    (rather than re-deriving it elsewhere) keeps the disclosure attached to
    the correct image through layout/export/reflow.
    """
    if not isinstance(image_ref, str) or not image_ref.strip():
        raise ImageProvenanceError("image_ref must be non-empty text")
    if not isinstance(provenance, ImageProvenance):
        raise ImageProvenanceError("provenance must be an ImageProvenance")
    text = student_visible_caption(provenance) if caption_text is None else caption_text
    if not isinstance(text, str) or not text.strip():
        raise ImageProvenanceError("caption_text must be non-empty text")
    return {
        "image_ref": image_ref.strip(),
        "caption_text": text,
        "provenance": provenance.to_dict(),
    }
