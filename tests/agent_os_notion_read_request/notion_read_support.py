"""Shared bounded helpers for the #2283 GitHub-controlled Notion read tests.

Nothing here touches a network, a credential, or a live Notion workspace. The
"verified" catalog is a test-only mutation of the repository-owned catalog: the
shipped catalog deliberately carries no verified binding, because live
secret-backed access remains a separately authorized excluded surface.
"""

from __future__ import annotations

import copy

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
ISSUE = 2283
UNIT_PAGE_ID = "11111111-1111-1111-1111-111111111111"
VISUAL_ASSETS_REQUEST = "photography-foundations-visual-assets"
CANONICAL_UNIT_REQUEST = "photography-foundations-canonical-unit"
GENERATED_AT = "2026-09-11T18:00:00Z"

APPROVED_ASSET = "asset-photography-contrast-01"
UNAPPROVED_ASSET = "asset-photography-unapproved-02"


def verified_payload(catalog_payload: dict) -> dict:
    payload = copy.deepcopy(catalog_payload)
    for unit in payload["canonical_units"]:
        unit["provider_page_id"] = UNIT_PAGE_ID
        unit["verification_state"] = "verified-current"
    for source in payload["sources"]:
        source["data_source_id"] = "ds-" + source["logical_source"]
        source["verification_state"] = "verified-current"
    return payload


def transport(
    *,
    request_id: str = VISUAL_ASSETS_REQUEST,
    repository: str = REPOSITORY,
    actor: str = ACTOR,
    issue_number: int = ISSUE,
    run_attempt: int = 1,
    status: str = "accepted",
    reason: str = "accepted-notion-read-envelope",
    **overrides: object,
) -> dict[str, object]:
    """Build one transport envelope shaped exactly like the governed ingress."""
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "status": status,
        "reason": reason,
        "repository": repository,
        "issue_number": issue_number,
        "comment_id": 991,
        "actor": actor,
        "handoff_id_or_none": None,
        "logical_trigger_id_or_none": "issue-comment-trigger:" + "a" * 64,
        "run_attempt": run_attempt,
        "dev_validation_branch_or_none": None,
        "dev_validation_sha_or_none": None,
        "dev_validation_id_or_none": None,
        "source_capsule_id_or_none": None,
        "notion_read_request_id_or_none": request_id,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }
    payload.update(overrides)
    return payload


def unit_page(
    *,
    page_id: str = UNIT_PAGE_ID,
    title: str = "Photography Foundations",
    archived: bool = False,
    human_review_required: bool = False,
) -> dict:
    """One live-shaped canonical-unit page payload.

    A title is required for an ``active`` unit: the canonical normalizer treats
    an untitled page (display name falling back to the id) as human-review
    evidence, which #973 then routes to ``needs-decision``.
    """
    return {
        "id": page_id,
        "title": title,
        "archived": archived,
        "human_review_required": human_review_required,
        "last_edited_time": "2026-09-10T12:00:00.000Z",
    }


class RecordingExecutor:
    """Records every bounded read payload the seam dispatches."""

    def __init__(
        self,
        *,
        assets: list[dict] | None = None,
        page_id: str = UNIT_PAGE_ID,
        page: dict | None = None,
    ):
        self.calls: list[dict] = []
        self.factory_invocations = 0
        self._assets = assets if assets is not None else default_assets()
        self._page_id = page_id
        self._page = page if page is not None else unit_page(page_id=page_id)

    def factory(self):
        self.factory_invocations += 1
        return self.execute

    def execute(self, payload):
        self.calls.append(copy.deepcopy(dict(payload)))
        if payload["action"] == "get_page":
            return {"status": "success", "output": copy.deepcopy(self._page)}
        return {"status": "success", "output": {"results": copy.deepcopy(self._assets)}}

    @property
    def actions(self) -> list[str]:
        return [str(call["action"]) for call in self.calls]


class ExplodingExecutor:
    """Fails the test if any secret-bearing composition is even constructed."""

    def factory(self):  # pragma: no cover - must never run
        raise AssertionError(
            "credential-bearing executor was built before admission succeeded"
        )


def default_assets() -> list[dict]:
    return [
        {
            "asset_id": APPROVED_ASSET,
            "exists": True,
            "approved_for_requested_use": True,
            "approved_student_reuse": True,
            "source_revision": 3,
            "canonical_unit_relation": True,
        },
        {
            "asset_id": UNAPPROVED_ASSET,
            "exists": True,
            "approved_for_requested_use": False,
            "approved_student_reuse": False,
            "source_revision": 2,
            "canonical_unit_relation": True,
        },
    ]
