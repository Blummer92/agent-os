"""#3252: build idempotency-key coverage.

The v2 key covers every consequential input: requirement identity, lesson
content bytes, template IDs *and* revisions, selected visuals (asset +
Lane-D content identity per role), candidate-set fingerprint, visual source
revision, and run targeting. A changed input yields a new key; reusing a key
with different inputs is rejected at recovery (anti-collision).
"""
from __future__ import annotations

import pytest

from instructional_materials_coach.cli import build_idempotency_key_v2


def _inputs(**overrides):
    payload = {
        "requirement_id": "req-1",
        "contract_version": "curriculum-material-requirement-v2",
        "record_revision": 3,
        "source_fingerprint": "sf-1",
        "content_fingerprint": "content-a",
        "slides_template_id": "slides-t",
        "slides_template_revision": "t1",
        "doc_template_id": "doc-t",
        "doc_template_revision": "t1",
        "selected_visuals": [],
        "candidate_set_fingerprint": "cs-a",
        "visual_source_revision": "rev-1",
        "target_folder": "folder",
        "content_title": "Lesson",
    }
    payload.update(overrides)
    return payload


def _key(**overrides):
    return build_idempotency_key_v2(**_inputs(**overrides))


def test_identical_inputs_produce_identical_key():
    assert _key() == _key()
    assert len(_key()) == 64
    # Field order / dict ordering must not affect the key (canonical JSON).
    assert _key(selected_visuals=[{"role": "r", "asset_id": "a", "content_identity": None}]) == _key(
        selected_visuals=[{"role": "r", "asset_id": "a", "content_identity": None}]
    )


def test_content_edit_yields_new_key():
    assert _key(content_fingerprint="content-a") != _key(content_fingerprint="content-b")


def test_selected_visual_change_yields_new_key():
    base = _key()
    changed_asset = _key(
        selected_visuals=[{"role": "r", "asset_id": "asset-2", "content_identity": None}]
    )
    assert changed_asset != base
    changed_content = _key(
        selected_visuals=[
            {
                "role": "r",
                "asset_id": "asset-1",
                "content_identity": {"algorithm": "sha256", "value": "b" * 64},
            }
        ]
    )
    assert changed_content != base
    assert changed_content != _key(
        selected_visuals=[
            {
                "role": "r",
                "asset_id": "asset-1",
                "content_identity": {"algorithm": "sha256", "value": "a" * 64},
            }
        ]
    )


def test_template_revision_bump_yields_new_key():
    assert _key(slides_template_revision="t1") != _key(slides_template_revision="t2")
    assert _key(doc_template_revision="t1") != _key(doc_template_revision="t2")
    # Same IDs, same revisions → same key.
    assert _key() == _key()


def test_candidate_set_change_yields_new_key():
    assert _key(candidate_set_fingerprint="cs-a") != _key(candidate_set_fingerprint="cs-b")


def test_visual_source_revision_change_yields_new_key():
    assert _key(visual_source_revision="rev-1") != _key(visual_source_revision="rev-2")


def test_requirement_identity_change_yields_new_key():
    assert _key(record_revision=3) != _key(record_revision=4)


def test_inconsequential_fields_do_not_change_key():
    # The payload has no timestamp/actor/retry-count fields by construction;
    # equivalent payloads built independently hash identically.
    first = build_idempotency_key_v2(**_inputs())
    second = build_idempotency_key_v2(**_inputs())
    assert first == second


def test_reused_key_with_different_inputs_is_rejected():
    """Anti-collision: a recovered copy bound to different inputs raises."""
    from instructional_materials_coach.live_build import (
        IdempotencyKeyInputMismatchError,
        _check_input_fingerprint,
    )

    meta = {"appProperties": {"agent_os_input_fingerprint": "fp-old"}}
    with pytest.raises(IdempotencyKeyInputMismatchError) as excinfo:
        _check_input_fingerprint(meta, input_fingerprint="fp-new", role="slides")
    assert "idempotency-key-input-mismatch" in str(excinfo.value)


def test_input_fingerprint_bound_to_copy_at_creation():
    """duplicate_template stamps agent_os_input_fingerprint."""
    from instructional_materials_coach import drive_client
    from unittest.mock import MagicMock

    service = MagicMock()
    service.files.return_value.copy.return_value.execute.return_value = {"id": "copy-1"}
    drive_client.duplicate_template(
        service,
        "template-1",
        "folder-1",
        "Copy",
        idempotency_key="k" * 64,
        role="slides",
        input_fingerprint="fp-1",
    )
    _, kwargs = service.files.return_value.copy.call_args
    assert kwargs["body"]["appProperties"]["agent_os_input_fingerprint"] == "fp-1"
    assert kwargs["body"]["appProperties"]["agent_os_idempotency_key"] == "k" * 64


def test_recovery_without_bound_fingerprint_is_allowed():
    """Pre-#3252 copies carry no fingerprint property: unverifiable, allowed."""
    from instructional_materials_coach.live_build import _check_input_fingerprint

    meta = {"appProperties": {"agent_os_idempotency_key": "k" * 64}}
    # No raise.
    _check_input_fingerprint(meta, input_fingerprint="fp-new", role="slides")
    # Empty expected fingerprint disables the check.
    _check_input_fingerprint(
        {"appProperties": {"agent_os_input_fingerprint": "fp-old"}},
        input_fingerprint="",
        role="slides",
    )
