"""Build pure Slides requests for text plus approved canonical visual reuse.

Callers must duplicate the template first. This module performs no I/O, asset
upload, registry mutation, or template mutation itself.
"""
from __future__ import annotations

from .asset_registry import NormalizedAsset, authorize_reuse
from .content_spec import LessonContent


def build_slides_replace_requests(content: LessonContent) -> list[dict]:
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


def build_slides_image_requests(
    content: LessonContent,
    assets_by_id: dict[str, NormalizedAsset],
) -> tuple[list[dict], tuple[str, ...]]:
    """Build replaceImage requests only for explicitly referenced, approved assets."""
    requests: list[dict] = []
    reused: list[str] = []
    for visual in content.visuals:
        asset = assets_by_id.get(visual.asset_id)
        if asset is None:
            raise ValueError(f"visual asset requires manual review: {visual.asset_id}: asset-not-found")
        allowed, reasons = authorize_reuse(asset)
        if not allowed:
            raise ValueError(
                f"visual asset requires manual review: {visual.asset_id}: {','.join(reasons)}"
            )
        if asset.disposition.lower() == "alternate":
            raise ValueError(
                f"visual asset requires manual review: {visual.asset_id}: alternate-requires-explicit-planner-selection"
            )
        requests.append(
            {
                "replaceImage": {
                    "imageObjectId": visual.target_object_id,
                    "url": asset.drive_uri,
                    "imageReplaceMethod": "CENTER_INSIDE",
                }
            }
        )
        reused.append(asset.asset_id)
    return requests, tuple(reused)
