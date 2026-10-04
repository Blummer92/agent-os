"""Visual-asset registration composition tests (#3254, Lane F).

Proves the real end-to-end composition with INJECTED clients (no live I/O):

    coordinator.coordinate_ingestion (#954, injected drive/library steps)
      -> identity_evidence_for_drive_file (#3256, Drive SHA-256 capture)
      -> issue_reusable_visual_identity (#3256, canonical mint)
      -> visual-asset-drive-writer write_asset (#958, injected Drive client)
      -> visual-asset-notion-writer write_asset (#959, injected Notion client,
         binding the issued asset_id to the governed "Asset ID" property)
      -> project_ingestion_admission (#3266, verified-record -> admission evidence)

The gap under test: on current main the ingestion coordinator returns
FULLY_SYNCHRONIZED with no admission evidence, and no repository
composition wires the issuer / identity evidence / writers / admission
projection end to end -- so an ingested approved asset never becomes an
eligible candidate through any production path. The money test below fails
until the composition module exists and passes only through the real
composition (injected in-memory clients; every component is the real one).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# The visual-asset-* tooling packages live in 08_Tooling/<pkg>/src (not on the
# root PYTHONPATH). Wire them explicitly so this test composes the REAL
# coordinator and writers rather than stubs.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _pkg in (
    "visual-asset-ingestion-coordinator",
    "visual-asset-drive-writer",
    "visual-asset-notion-writer",
):
    _src = str(_REPO_ROOT / "08_Tooling" / _pkg / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

from visual_asset_drive_writer.writer import DriveFileEvidence  # noqa: E402
from visual_asset_notion_writer.writer import (  # noqa: E402
    NotionPageEvidence,
    NotionPropertySpec,
)

from navigation_registry.connectors.notion_asset_evidence_projection import (  # noqa: E402
    project_notion_asset_page,
)
from navigation_registry.connectors.visual_asset_registration_composition import (  # noqa: E402
    RegistrationIntake,
    register_visual_asset,
)

SHA256 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
DATA_SOURCE_ID = "da5cba48-50fd-4377-9790-8df8f6f2c7dd"
CANONICAL_RE = re.compile(r"^visual-asset-[0-9a-f]{24}$")


class FakeDriveClient:
    """In-memory DriveClient protocol implementation. No I/O."""

    def __init__(self) -> None:
        self._files: dict[str, DriveFileEvidence] = {}
        self._counter = 0
        self.create_calls = 0

    def find_by_operation_key(self, operation_key: str) -> tuple[DriveFileEvidence, ...]:
        return tuple(f for f in self._files.values() if f.operation_key == operation_key)

    def reserve_file_id(self) -> str:
        self._counter += 1
        return f"fake-drive-file-{self._counter:04d}"

    def create_file(self, *, file_id: str, request, operation_key: str) -> None:
        self.create_calls += 1
        self._files[file_id] = DriveFileEvidence(
            file_id=file_id,
            parent_folder_id=request.parent_folder_id,
            mime_type=request.mime_type,
            content_sha256=request.content_sha256,
            operation_key=operation_key,
        )

    def fetch_file(self, file_id: str) -> DriveFileEvidence | None:
        return self._files.get(file_id)


def _notion_schema() -> tuple[NotionPropertySpec, ...]:
    return (
        NotionPropertySpec(name="Asset ID", property_type="rich_text"),
        NotionPropertySpec(name="Drive File ID", property_type="rich_text"),
        NotionPropertySpec(name="Asset Title", property_type="title"),
        NotionPropertySpec(name="Concept", property_type="rich_text"),
        NotionPropertySpec(name="Import Notes", property_type="rich_text"),
    )


class FakeNotionClient:
    """In-memory NotionClient protocol implementation. No I/O.

    Stores exactly what the writer wrote (property name -> MetadataValue
    pairs), so a simulated "next run" bounded read projects from the real
    written state.
    """

    def __init__(self) -> None:
        self._pages: dict[str, NotionPageEvidence] = {}
        self._counter = 0

    def fetch_schema(self, data_source_id: str) -> tuple[NotionPropertySpec, ...]:
        assert data_source_id == DATA_SOURCE_ID
        return _notion_schema()

    def find_exact(self, *, data_source_id: str, property_name: str, value: str):
        assert data_source_id == DATA_SOURCE_ID
        return tuple(
            page
            for page in self._pages.values()
            if dict(page.properties).get(property_name) == value
        )

    def create_page(self, *, data_source_id: str, properties, operation_key: str) -> str:
        assert data_source_id == DATA_SOURCE_ID
        self._counter += 1
        page_id = f"11111111-2222-3333-4444-{self._counter:012d}"
        self._pages[page_id] = NotionPageEvidence(page_id=page_id, properties=tuple(properties))
        return page_id

    def update_page(self, *, page_id: str, properties) -> None:
        current = dict(self._pages[page_id].properties)
        current.update(dict(properties))
        self._pages[page_id] = NotionPageEvidence(page_id=page_id, properties=tuple(current.items()))

    def fetch_page(self, page_id: str) -> NotionPageEvidence | None:
        return self._pages.get(page_id)


def approved_intake(**changes) -> RegistrationIntake:
    data = dict(
        intake_reference="intake-3254-proof",
        local_reference="generation-handoff-7/asset.png",
        content_sha256=SHA256,
        mime_type="image/png",
        parent_folder_id="drive-library-folder-1",
        provenance={
            "source_reference": "generation-handoff-7",
            "source_fingerprint": "b" * 64,
            "evidence_reference": "teacher-review-7",
        },
        lineage={"kind": "original", "predecessor_asset_id": None, "predecessor_stable_ref": None},
        governed_asset_id=None,
        asset_title="Candy brand motion spot key visual",
        concept="brand-to-motion statement",
        source_approved=True,
        reusable_across_units=True,
        reuse_status="reusable",
        reuse_scope="coursewide",
        notion_data_source_id=DATA_SOURCE_ID,
        dry_run=False,
    )
    data.update(changes)
    return RegistrationIntake(**data)


def _raw_page(page_id: str, stored: dict) -> dict:
    """Simulate the bounded read's raw Notion API shape from stored pairs."""
    properties = {}
    for name, value in stored.items():
        if name == "Asset Title":
            properties[name] = {"type": "title", "title": [{"plain_text": value}]}
        else:
            properties[name] = {"type": "rich_text", "rich_text": [{"plain_text": value}]}
    return {"id": page_id, "properties": properties}


# ---------------------------------------------------------------------------
# The money test: ingest -> next-plan-selects through the REAL composition.
# ---------------------------------------------------------------------------


def test_ingested_approved_asset_becomes_eligible_candidate_through_composition():
    drive = FakeDriveClient()
    notion = FakeNotionClient()

    result = register_visual_asset(
        intake=approved_intake(), drive_client=drive, notion_client=notion
    )

    assert result.state == "registered", result.reason_codes
    assert result.asset_id is not None and CANONICAL_RE.fullmatch(result.asset_id)
    assert result.drive_file_id is not None
    assert result.page_id is not None
    # The drive write really happened through the injected client.
    assert drive.create_calls == 1

    # Admission evidence was projected from the verified record.
    admission = result.admission
    assert admission is not None
    assert admission.kind == "evidence", admission.gaps
    assert admission.evidence["asset_id"] == result.asset_id

    # Next run: the bounded read of the written page projects to an eligible
    # candidate carrying the governed (canonical) Asset ID -- the exact tuple
    # #3257 placement consumes: (Asset ID, page ID, Drive file ID).
    stored_page = notion.fetch_page(result.page_id)
    assert stored_page is not None
    projected = project_notion_asset_page(
        _raw_page(result.page_id, dict(stored_page.properties)),
        relation_first=False,
        reuse_scope="coursewide",
    )
    assert projected.kind == "evidence", projected.gaps
    assert projected.evidence["asset_id"] == result.asset_id
    assert projected.evidence["library_reference"]["drive_file_id"] == result.drive_file_id


def test_composition_admission_evidence_is_selected_by_next_plan_run():
    """Amended acceptance criterion: the admission evidence produced by the
    REAL composition (not a hand-built dict) is admitted by the #3253
    assembler on the next plan run."""
    from instructional_workflow_contracts.current_curriculum_evidence import (
        assemble_current_curriculum_evidence,
    )

    drive = FakeDriveClient()
    notion = FakeNotionClient()
    result = register_visual_asset(
        intake=approved_intake(), drive_client=drive, notion_client=notion
    )
    assert result.state == "registered"
    assert result.admission is not None and result.admission.kind == "evidence"
    assert result.admission.evidence is not None

    packet = assemble_current_curriculum_evidence(
        request={
            "action": "images",
            "artifact_type": "images",
            "relative_time": "none",
            "requires_reusable_assets": True,
        },
        canonical_unit={"stable_id": "photography-foundations", "status": "active"},
        owner_evidence=[],
        asset_evidence=[result.admission.evidence],
    )
    assert [item["asset_id"] for item in packet["asset_evidence"]] == [result.asset_id]


def test_composition_is_idempotent_across_reruns():
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    first = register_visual_asset(intake=approved_intake(), drive_client=drive, notion_client=notion)
    second = register_visual_asset(intake=approved_intake(), drive_client=drive, notion_client=notion)
    assert first.state == "registered"
    assert second.state == "registered"
    # Same evidence -> same canonical identity; writers reconciled, no duplicate.
    assert second.asset_id == first.asset_id
    assert second.page_id == first.page_id
    assert drive.create_calls == 1


# ---------------------------------------------------------------------------
# Asset ID policy: governed property is authoritative input; canonical mint;
# legacy values are external aliases; unknown values fail closed.
# ---------------------------------------------------------------------------


def test_governed_canonical_asset_id_reconciles():
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    first = register_visual_asset(intake=approved_intake(), drive_client=drive, notion_client=notion)
    assert first.state == "registered"
    # Re-ingest a record that already carries the governed canonical ID.
    second = register_visual_asset(
        intake=approved_intake(governed_asset_id=first.asset_id),
        drive_client=drive,
        notion_client=notion,
    )
    assert second.state == "registered", second.reason_codes
    assert second.asset_id == first.asset_id
    assert "registration-asset-id-reconciled" in second.reason_codes


def test_governed_canonical_asset_id_conflict_fails_closed():
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    result = register_visual_asset(
        intake=approved_intake(governed_asset_id="visual-asset-" + "0" * 24),
        drive_client=drive,
        notion_client=notion,
    )
    assert result.state == "failed"
    assert "registration-asset-id-conflict" in result.reason_codes
    assert result.admission is None
    # Nothing was written to Notion: the conflict failed before the library step.
    assert notion.fetch_page("11111111-2222-3333-4444-000000000001") is None


@pytest.mark.parametrize("legacy", ["VA-20260926-0044", "DMIMG-1a2B3c4D5e6F7g8H9i0J"])
def test_legacy_asset_id_passes_through_as_external_alias(legacy):
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    result = register_visual_asset(
        intake=approved_intake(governed_asset_id=legacy),
        drive_client=drive,
        notion_client=notion,
    )
    assert result.state == "registered", result.reason_codes
    # Canonical identity is minted; the legacy value is never minted and never
    # validated as canonical -- it rides along as a recognized external alias
    # with explicit provenance.
    assert CANONICAL_RE.fullmatch(result.asset_id or "")
    assert len(result.external_aliases) == 1
    alias = result.external_aliases[0]
    assert alias.value == legacy
    assert "never minted" in alias.provenance
    assert "registration-asset-id-legacy-alias" in result.reason_codes
    # The governed property is bound to the canonical identity.
    stored = notion.fetch_page(result.page_id)
    assert stored is not None
    assert dict(stored.properties)["Asset ID"] == result.asset_id


def test_unknown_asset_id_format_fails_closed_as_incomplete_evidence():
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    result = register_visual_asset(
        intake=approved_intake(governed_asset_id="mystery-12345"),
        drive_client=drive,
        notion_client=notion,
    )
    assert result.state == "failed"
    assert "registration-asset-id-unrecognized" in result.reason_codes
    assert result.admission is None


def test_missing_sha256_fails_closed_before_any_write():
    drive = FakeDriveClient()
    notion = FakeNotionClient()

    class NoHashDrive(FakeDriveClient):
        def create_file(self, *, file_id, request, operation_key):
            # Stores the file but reports no usable hash on readback.
            self._files[file_id] = DriveFileEvidence(
                file_id=file_id,
                parent_folder_id=request.parent_folder_id,
                mime_type=request.mime_type,
                content_sha256="",
                operation_key=operation_key,
            )

    result = register_visual_asset(
        intake=approved_intake(), drive_client=NoHashDrive(), notion_client=notion
    )
    assert result.state == "failed"
    assert "registration-drive-unverified" in result.reason_codes


def test_dry_run_writes_nothing():
    drive = FakeDriveClient()
    notion = FakeNotionClient()
    result = register_visual_asset(
        intake=approved_intake(dry_run=True), drive_client=drive, notion_client=notion
    )
    assert result.state == "dry-run"
    assert drive.create_calls == 0
    assert result.page_id is None
    assert result.admission is None
