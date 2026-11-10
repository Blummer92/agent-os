"""Verified VAL field-mapping contract fixture (#3254).

Pins the 2026-10-13 live Visual Asset Library schema (GitHub Actions run
38395806356, "Agent OS Bounded Notion Read", 24 properties, conclusion success,
head 3123ce71) against the governed projection vocabulary in
``navigation_registry.connectors.notion_asset_evidence_projection``.

Test-only fixture: this file changes no production behavior. Every assertion
exercises the real projection. Unresolved field semantics are pinned as
UNRESOLVED-reads-as-absent -- never guessed, never silently mapped. The three
open owner semantic decisions (#3254 admission questions Q1-Q3) are named in
the relevant tests; when Zachary resolves one, the corresponding test here must
be updated to the decided mapping -- a failing test then is the intended
signal, not a regression.

Honesty boundary: these tests pin the name/type contract as observed on
2026-10-13. They do not prove live VAL records carry any particular values.
"""

from navigation_registry.connectors.notion_asset_evidence_projection import (
    APPROVED_USE_PROPERTY,
    ASSET_ID_PROPERTY,
    ASSET_TITLE_PROPERTY,
    CANONICAL_UNIT_PROPERTY,
    COGNITIVE_LOAD_PROPERTY,
    DRIVE_FILE_ID_PROPERTY,
    HUMAN_REVIEW_DONE_PROPERTY,
    REUSABLE_ACROSS_UNITS_PROPERTY,
    REUSE_STATUS_PROPERTY,
    SCOPE_UNIT_IDS_PROPERTY,
    STYLE_FAMILY_PROPERTY,
    VISUAL_ASSET_LIBRARY_PROPERTIES,
    _REUSE_STATUS_APPROVED_VALUES,
    _REUSE_STATUS_DENIED_VALUES,
    project_approval,
    project_drive_file_id,
    project_notion_asset_page,
    project_scope_unit_ids,
)

# Verified 2026-10-13 from run 38395806356 (property MR%3Do, select).
# Provenance: "Publish bounded Notion read evidence" step raw log.
VERIFIED_REUSE_STATUS_OPTIONS = {
    "dd905330-8147-4f98-b1e5-20552f7d8b13": "approved",
    "a0f0a782-c5a9-4f21-8464-516710793c28": "draft",
    "ccac6124-dbfb-479b-9b29-989d6044d9ad": "needs revision",
    "50f83a5c-b31f-4baf-aee2-9effc04ff8d6": "retired",
}

# Verified 2026-10-13 from run 38395806356 (24 properties). Names are exact;
# Notion property-name matching is case-sensitive.
VERIFIED_LIVE_PROPERTY_NAMES = {
    "Accessibility notes",
    "Unit / lesson / material type",
    "Canonical Unit",
    "Approved use",
    "Asset type",
    "Reuse status",
    "AI Metadata Status",
    "Thumbnail",
    "Editable source link",
    "Review Date",
    "Keywords",
    "Source file link in Google Drive",
    "Cognitive load rating",
    "Prompt Source",
    "AI Prompt",
    "Alt text",
    "Style family",
    "Source Authority Notes",
    "Human Review Status",
    "Instructional purpose",
    "Version",
    "file_id",
    "Reviewer",
    "Asset title",
}


def _reuse_status_props(name, option_id=None):
    option = {"name": name}
    if option_id is not None:
        option["id"] = option_id
    return {"Reuse status": {"id": "MR%3Do", "type": "select", "select": option}}


def test_exact_match_property_names():
    """The five verified-exact bindings hold on current main."""
    assert REUSE_STATUS_PROPERTY == "Reuse status"
    assert APPROVED_USE_PROPERTY == "Approved use"
    assert STYLE_FAMILY_PROPERTY == "Style family"
    assert COGNITIVE_LOAD_PROPERTY == "Cognitive load rating"
    assert CANONICAL_UNIT_PROPERTY == "Canonical Unit"
    for name in (
        REUSE_STATUS_PROPERTY,
        APPROVED_USE_PROPERTY,
        STYLE_FAMILY_PROPERTY,
        COGNITIVE_LOAD_PROPERTY,
        CANONICAL_UNIT_PROPERTY,
    ):
        assert name in VERIFIED_LIVE_PROPERTY_NAMES


def test_reuse_status_option_table():
    """All four verified option id->name pairs; exactly one approval value."""
    assert len(VERIFIED_REUSE_STATUS_OPTIONS) == 4
    assert _REUSE_STATUS_APPROVED_VALUES == {"approved"}
    assert _REUSE_STATUS_DENIED_VALUES == {"denied", "rejected", "revoked"}
    approved_ids = [
        oid for oid, name in VERIFIED_REUSE_STATUS_OPTIONS.items() if name == "approved"
    ]
    assert approved_ids == ["dd905330-8147-4f98-b1e5-20552f7d8b13"]


def test_project_approval_approved_is_true():
    requested, _student = project_approval(
        _reuse_status_props("approved", "dd905330-8147-4f98-b1e5-20552f7d8b13")
    )
    assert requested is True


def test_project_approval_other_options_are_not_approved():
    for oid, name in VERIFIED_REUSE_STATUS_OPTIONS.items():
        if oid == "dd905330-8147-4f98-b1e5-20552f7d8b13":
            continue
        requested, _student = project_approval(_reuse_status_props(name, oid))
        assert requested is None, name


def test_project_approval_denied_values_are_false():
    for name in ("denied", "rejected", "revoked"):
        requested, _student = project_approval(_reuse_status_props(name))
        assert requested is False, name


def test_missing_asset_id_projects_incomplete_evidence():
    """No governed Asset ID -> explicit gap; the page UUID is never substituted."""
    page = {"id": "00000000-0000-4000-8000-000000000001", "properties": {}}
    projected = project_notion_asset_page(page, relation_first=True, reuse_scope=None)
    assert projected.kind == "incomplete-evidence"
    assert projected.evidence is None
    assert projected.page_id == "00000000-0000-4000-8000-000000000001"
    assert "identity: no governed Asset ID on the Notion record" in projected.gaps


def test_file_id_is_never_consumed_as_drive_binding():
    """UNRESOLVED Q1: live `file_id` must not silently become the drive binding."""
    assert DRIVE_FILE_ID_PROPERTY == "Drive File ID"
    assert DRIVE_FILE_ID_PROPERTY not in VERIFIED_LIVE_PROPERTY_NAMES
    # A record carrying only the live `file_id` still has no drive binding.
    assert (
        project_drive_file_id(
            {"file_id": {"rich_text": [{"plain_text": "1AbC2DeF3GhI"}]}}
        )
        is None
    )


def test_asset_title_case_mismatch_reads_absent():
    """UNRESOLVED Q2: projection reads "Asset Title"; live schema has "Asset title"."""
    assert ASSET_TITLE_PROPERTY == "Asset Title"
    assert ASSET_TITLE_PROPERTY not in VERIFIED_LIVE_PROPERTY_NAMES
    assert "Asset title" in VERIFIED_LIVE_PROPERTY_NAMES


def test_human_review_status_reads_absent():
    """UNRESOLVED Q3: projection expects "Human Review Done"; live has
    "Human Review Status" (status type). It must read as absent, not mapped."""
    assert HUMAN_REVIEW_DONE_PROPERTY == "Human Review Done"
    assert HUMAN_REVIEW_DONE_PROPERTY not in VERIFIED_LIVE_PROPERTY_NAMES
    requested, _student = project_approval(
        {"Human Review Status": {"status": {"name": "Complete"}}}
    )
    assert requested is None


def test_vocabulary_admission_facts():
    """Pins the #3253 coursewide boundary: "Reuse status" is in-vocabulary,
    "Reusable Across Units?" is not."""
    assert REUSE_STATUS_PROPERTY in VISUAL_ASSET_LIBRARY_PROPERTIES
    assert REUSABLE_ACROSS_UNITS_PROPERTY not in VISUAL_ASSET_LIBRARY_PROPERTIES


def test_scope_unit_ids_absent():
    assert SCOPE_UNIT_IDS_PROPERTY == "Scope Unit IDs"
    assert SCOPE_UNIT_IDS_PROPERTY not in VERIFIED_LIVE_PROPERTY_NAMES
    assert project_scope_unit_ids({}) == ()
