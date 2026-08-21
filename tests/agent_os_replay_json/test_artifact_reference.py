from __future__ import annotations

import json

import pytest

from scripts.agent_os_replay_json.artifact_reference import (
    RecorderPipelineStatuses,
    build_artifact_ref,
    build_notion_projection,
    fingerprint_artifact,
    validate_lineage,
    verify_artifact_bytes,
)

SOURCE = b'{"title":"Tutorial 0","steps":[{"type":"navigate","url":"https://example.invalid/private"}]}'
CLEAN = b'{"title":"Tutorial 0","steps":[{"type":"navigate","url":"https://example.invalid/safe"}]}'


def _source(ref: str = "local://tutorial-0/original.json"):
    return build_artifact_ref(SOURCE, artifact_ref=ref, privacy_review_state="restricted", display_name="Tutorial 0 - Organization Core")


def _clean(parent=None, ref: str = "local://tutorial-0/rj2-cleaned.json"):
    parent = parent or _source()
    return build_artifact_ref(CLEAN, artifact_ref=ref, privacy_review_state="reviewed-safe-reference", parent=parent, derivation_kind="rj2-cleaned", display_name="Tutorial 0 - Organization Core (RJ2)")


def test_sha256_is_deterministic_and_filename_independent() -> None:
    assert fingerprint_artifact(SOURCE) == fingerprint_artifact(bytes(SOURCE))
    assert _source("local://a.json").sha256 == _source("drive://file-123/rev-7").sha256
    assert _source("local://a.json").recording_id == _source("drive://file-123/rev-7").recording_id


def test_byte_change_changes_content_identity() -> None:
    assert fingerprint_artifact(SOURCE) != fingerprint_artifact(CLEAN)


def test_derived_artifact_has_exact_parent_and_distinct_identity() -> None:
    parent = _source()
    child = _clean(parent)
    assert child.parent_sha256 == parent.sha256
    assert child.sha256 != parent.sha256
    assert validate_lineage(parent, child)


def test_original_cannot_claim_derivation_or_overwrite_identity() -> None:
    with pytest.raises(ValueError, match="derivation_kind requires parent"):
        build_artifact_ref(SOURCE, artifact_ref="local://x", derivation_kind="rj2-cleaned")
    parent = _source()
    with pytest.raises(ValueError, match="reference itself"):
        build_artifact_ref(SOURCE, artifact_ref="local://same", parent=parent, derivation_kind="rj2-cleaned")


def test_stale_or_fake_parent_digest_is_rejected() -> None:
    parent = _source()
    other_parent = build_artifact_ref(b"other", artifact_ref="local://other")
    child = _clean(parent)
    with pytest.raises(ValueError, match="parent digest mismatch"):
        validate_lineage(other_parent, child)


def test_cycle_is_rejected() -> None:
    parent = _source()
    child = _clean(parent)
    with pytest.raises(ValueError, match="cycle"):
        validate_lineage(parent, child, ancestor_digests=(child.sha256,))


def test_provider_location_change_preserves_content_identity() -> None:
    local = _source("local://tutorial/original.json")
    drive = _source("drive://opaque-file-id/revision-2")
    assert local.sha256 == drive.sha256
    assert local.artifact_ref != drive.artifact_ref


def test_same_provider_path_with_changed_bytes_detects_drift() -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_artifact_bytes(_source("drive://file-id/revision-2"), CLEAN)


def test_truncated_source_cannot_pass_verification() -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_artifact_bytes(_source(), SOURCE[:-1])


def test_exact_bytes_verify() -> None:
    assert verify_artifact_bytes(_source(), SOURCE)


def test_statuses_keep_unknown_layers_explicit() -> None:
    statuses = RecorderPipelineStatuses(rj1="analyzed", rj2="cleaned-candidate-available", rj3="pending", rj4="indeterminate")
    assert statuses.rj3 == "pending"
    assert statuses.rj4 == "indeterminate"


@pytest.mark.parametrize(("field", "value"), [("rj1", "success"), ("rj2", "success"), ("rj3", "unknown"), ("rj4", "proven")])
def test_invalid_statuses_fail_closed(field: str, value: str) -> None:
    values = {"rj1": "pending", "rj2": "pending", "rj3": "pending", "rj4": "pending"}
    values[field] = value
    with pytest.raises(ValueError, match=f"unsupported {field} status"):
        RecorderPipelineStatuses(**values)


def test_notion_projection_is_bounded_metadata_only() -> None:
    projection = build_notion_projection(_clean(), RecorderPipelineStatuses(rj1="analyzed", rj2="cleaned-candidate-available"), modeling_sequence_ref="teacher-modeling://tutorial-0", warnings=("Synthetic fixture only",))
    serialized = json.dumps(projection, sort_keys=True)
    assert "rewritten_recording" not in projection
    assert "steps" not in projection
    assert "selectors" not in serialized
    assert "typed" not in serialized
    assert "example.invalid" not in serialized
    assert projection["rj3"] == "pending"
    assert projection["rj4"] == "pending"


def test_projection_does_not_emit_raw_source_bytes_or_urls() -> None:
    projection = build_notion_projection(_source(), RecorderPipelineStatuses(), modeling_sequence_ref="model://sequence")
    rendered = json.dumps(projection)
    assert SOURCE.decode() not in rendered
    assert "https://example.invalid/private" not in rendered


def test_projection_warning_count_is_bounded() -> None:
    projection = build_notion_projection(_source(), RecorderPipelineStatuses(), modeling_sequence_ref="model://sequence", warnings=tuple(f"warning-{i}" for i in range(20)))
    assert len(projection["warnings"]) == 8


def test_tutorial_zero_golden_lineage() -> None:
    original = _source()
    cleaned = _clean(original)
    projection = build_notion_projection(cleaned, RecorderPipelineStatuses(rj1="analyzed", rj2="cleaned-candidate-available", rj3="pending", rj4="pending"), modeling_sequence_ref="teacher-modeling://tutorial-0/organization-core")
    assert original.sha256 == fingerprint_artifact(SOURCE)
    assert cleaned.sha256 == fingerprint_artifact(CLEAN)
    assert cleaned.parent_sha256 == original.sha256
    assert projection["sha256"] == cleaned.sha256
    assert projection["parent_sha256"] == original.sha256
    assert "steps" not in projection
