"""Focused #1424 coverage for the offline Notion Compute Decision writer.

Covers the case list required by the #1424 issue contract: exact-identity
target resolution, title-only-match insufficiency, ambiguous/missing targets
fail closed with no create, stale/conflicting #1419 evidence is blocked,
every supported disposition maps to its exact #1420 presentation string,
unchanged values skip mutation, unrelated properties are preserved, a field
outside the allowlist is rejected, an ambiguous prior-write outcome
reconciles instead of blindly retrying, a readback mismatch is verification-
failed, identical input produces an identical plan, and dry-run/no-client
paths make zero external calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from notion_compute_decision_writer import (
    COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME,
    COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION,
    COMPUTE_DECISION_PRESENTATION,
    DATA_SOURCE_ID,
    CanonicalIdentity,
    ComputeDecisionWriteRequest,
    NotionPropertySpec,
    NotionRateLimitError,
    NotionTaskPageEvidence,
    NotionTransientError,
    PropertyBinding,
    WriteState,
    parse_compute_control_projection_evidence,
    plan_and_write_compute_decision,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE_NUMBER = 1424
HEAD_SHA = "a" * 40
SOURCE_LINK = f"https://github.com/{REPOSITORY}/issues/{ISSUE_NUMBER}"
SOURCE_LINK_PROPERTY = "Source Link"
COMPUTE_DECISION_PROPERTY = "Compute Decision"


class FakeNotionClient:
    def __init__(self, pages=(), *, schema=None, update_raises=None, apply_write_before_raise=False):
        self._pages = {page.page_id: page for page in pages}
        self._schema = schema or (
            NotionPropertySpec(COMPUTE_DECISION_PROPERTY, "rich_text"),
            NotionPropertySpec(SOURCE_LINK_PROPERTY, "url"),
        )
        self._update_raises = update_raises
        self._apply_write_before_raise = apply_write_before_raise
        self.update_calls = 0
        self.fetch_page_calls = 0
        self.find_exact_calls = 0
        self.fetch_schema_calls = 0
        self.last_update_properties = None

    def fetch_schema(self, data_source_id):
        self.fetch_schema_calls += 1
        assert data_source_id == DATA_SOURCE_ID
        return self._schema

    def find_exact(self, *, data_source_id, property_name, value):
        self.find_exact_calls += 1
        assert data_source_id == DATA_SOURCE_ID
        if property_name != SOURCE_LINK_PROPERTY:
            return ()
        return tuple(page for page in self._pages.values() if page.source_link == value)

    def update_page(self, *, page_id, properties):
        self.update_calls += 1
        self.last_update_properties = properties
        page = self._pages[page_id]
        updates = dict(properties)
        compute_decision = updates.get(COMPUTE_DECISION_PROPERTY, page.compute_decision)
        if self._update_raises is not None:
            exc, self._update_raises = self._update_raises, None
            if self._apply_write_before_raise:
                # Simulates the write actually landing server-side even
                # though the client observed a transient/rate-limit error.
                self._pages[page_id] = NotionTaskPageEvidence(page.page_id, page.source_link, compute_decision)
            raise exc
        self._pages[page_id] = NotionTaskPageEvidence(page.page_id, page.source_link, compute_decision)

    def fetch_page(self, page_id):
        self.fetch_page_calls += 1
        return self._pages.get(page_id)


class ExplodingClient:
    """Any call is a test failure -- used to prove a path makes zero client calls."""

    def fetch_schema(self, data_source_id):
        raise AssertionError("fetch_schema must not be called")

    def find_exact(self, **kwargs):
        raise AssertionError("find_exact must not be called")

    def update_page(self, **kwargs):
        raise AssertionError("update_page must not be called")

    def fetch_page(self, page_id):
        raise AssertionError("fetch_page must not be called")


def _projection_payload(
    *,
    disposition="run-now",
    reason_codes=(),
    repository=REPOSITORY,
    issue_number=ISSUE_NUMBER,
    current_head_sha=HEAD_SHA,
):
    return {
        "schema_name": COMPUTE_CONTROL_PROJECTION_SCHEMA_NAME,
        "schema_version": COMPUTE_CONTROL_PROJECTION_SCHEMA_VERSION,
        "repository": repository,
        "issue_number": issue_number,
        "current_head_sha": current_head_sha,
        "compute_disposition": disposition,
        "reason_codes": list(reason_codes),
    }


def _projection(**kwargs):
    return parse_compute_control_projection_evidence(_projection_payload(**kwargs))


def _identity(**overrides):
    defaults = dict(repository=REPOSITORY, issue_number=ISSUE_NUMBER, current_head_sha=HEAD_SHA)
    defaults.update(overrides)
    return CanonicalIdentity(**defaults)


def _binding(**overrides):
    defaults = dict(logical_field="compute_decision", property_name=COMPUTE_DECISION_PROPERTY, property_type="rich_text")
    defaults.update(overrides)
    return PropertyBinding(**defaults)


def _request(*, projection=None, dry_run=True, source_link=SOURCE_LINK, **overrides):
    kwargs = dict(
        data_source_id=DATA_SOURCE_ID,
        source_link=source_link,
        source_link_property_name=SOURCE_LINK_PROPERTY,
        expected_identity=_identity(),
        projection=projection if projection is not None else _projection(),
        compute_decision_binding=_binding(),
        dry_run=dry_run,
    )
    kwargs.update(overrides)
    return ComputeDecisionWriteRequest(**kwargs)


def _page(page_id="page-1", source_link=SOURCE_LINK, compute_decision=None):
    return NotionTaskPageEvidence(page_id, source_link, compute_decision)


# --- projection payload parsing -------------------------------------------------


def test_parse_projection_rejects_unsupported_schema():
    payload = _projection_payload()
    payload["schema_version"] = "9.9"
    with pytest.raises(ValueError):
        parse_compute_control_projection_evidence(payload)


def test_parse_projection_rejects_unsupported_disposition():
    payload = _projection_payload()
    payload["compute_disposition"] = "made-up-disposition"
    with pytest.raises(ValueError):
        parse_compute_control_projection_evidence(payload)


def test_parse_projection_rejects_malformed_head_sha():
    payload = _projection_payload()
    payload["current_head_sha"] = "not-a-sha"
    with pytest.raises(ValueError):
        parse_compute_control_projection_evidence(payload)


def test_parse_projection_allows_null_head_sha():
    payload = _projection_payload()
    payload["current_head_sha"] = None
    evidence = parse_compute_control_projection_evidence(payload)
    assert evidence.current_head_sha is None


# --- dry-run / zero external calls ----------------------------------------------


def test_dry_run_default_makes_zero_client_calls():
    request = _request(dry_run=True)
    result = plan_and_write_compute_decision(request, ExplodingClient())
    assert result.state == WriteState.DRY_RUN
    assert result.dry_run is True
    assert result.external_write_performed is False
    assert result.intended_value == "Run Now"


def test_dry_run_is_the_default_and_needs_no_client():
    request = _request(dry_run=True)
    result = plan_and_write_compute_decision(request)
    assert result.state == WriteState.DRY_RUN


def test_no_client_supplied_precheck_fails_without_touching_notion():
    request = _request(dry_run=False)
    result = plan_and_write_compute_decision(request, None)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-client-required" in result.reason_codes


# --- exact identity resolution / title insufficiency ----------------------------


def test_exact_source_link_identity_resolves_one_target_and_updates():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = FakeNotionClient(pages=(page,))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.UPDATED
    assert result.readback_verified is True
    assert result.intended_value == "Run Now"
    assert client.update_calls == 1


def test_title_only_match_is_insufficient():
    """A client that returns rows regardless of exact Source Link is still
    filtered down to exact-identity matches here; a same-titled but
    different-Source-Link row never resolves the target."""
    decoy = _page(page_id="decoy", source_link="https://github.com/other/repo/issues/1")
    client = FakeNotionClient(pages=(decoy,))
    request = _request(dry_run=False)
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-target-missing" in result.reason_codes
    assert client.update_calls == 0


def test_two_plausible_targets_is_ambiguous():
    first = _page(page_id="page-1")
    second = _page(page_id="page-2")
    client = FakeNotionClient(pages=(first, second))
    request = _request(dry_run=False)
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-target-ambiguous" in result.reason_codes
    assert client.update_calls == 0


def test_missing_target_is_blocked_and_never_creates():
    client = FakeNotionClient(pages=())
    request = _request(dry_run=False)
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-target-missing" in result.reason_codes
    # The client Protocol this writer depends on has no create method at all;
    # only fetch_schema/find_exact/update_page/fetch_page were exercised.
    assert client.update_calls == 0


# --- stale / conflicting #1419 evidence -----------------------------------------


def test_stale_projection_reason_code_blocks_before_any_target_read():
    client = FakeNotionClient(pages=(_page(),))
    projection = _projection(reason_codes=("compute.fail-closed-currentness",))
    request = _request(dry_run=False, projection=projection)
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-projection-stale-or-conflicting" in result.reason_codes
    assert client.find_exact_calls == 0
    assert client.update_calls == 0


def test_identity_mismatch_between_projection_and_expected_blocks():
    client = FakeNotionClient(pages=(_page(),))
    request = _request(dry_run=False, expected_identity=_identity(issue_number=9999))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-identity-mismatch" in result.reason_codes
    assert client.find_exact_calls == 0


# --- exact disposition -> presentation mapping ----------------------------------


@pytest.mark.parametrize(
    "disposition,expected_text",
    [
        ("run-now", "Run Now"),
        ("do-not-spend-compute-yet", "Do Not Spend Compute Yet"),
        ("focused-validation-first", "Focused Validation First"),
        ("final-cloud-validation-required", "Final Cloud Validation Required"),
        ("reuse-existing-evidence", "Reuse Existing Evidence"),
        ("duplicate-or-obsolete-run-risk", "Duplicate / Obsolete Run Risk"),
        ("unavailable", "Verify Current State"),
    ],
)
def test_every_supported_disposition_maps_to_its_exact_presentation(disposition, expected_text):
    assert COMPUTE_DECISION_PRESENTATION[disposition] == expected_text
    request = _request(dry_run=True, projection=_projection(disposition=disposition))
    result = plan_and_write_compute_decision(request)
    assert result.intended_value == expected_text


# --- unchanged-skip / unrelated-property preservation ---------------------------


def test_unchanged_value_skips_mutation():
    page = _page(compute_decision="Run Now")
    client = FakeNotionClient(pages=(page,))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.UNCHANGED_SKIP
    assert result.external_write_performed is False
    assert client.update_calls == 0


def test_update_only_ever_names_the_compute_decision_property():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = FakeNotionClient(pages=(page,))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    plan_and_write_compute_decision(request, client)
    assert client.last_update_properties == ((COMPUTE_DECISION_PROPERTY, "Run Now"),)


def test_source_link_is_never_written():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = FakeNotionClient(pages=(page,))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    plan_and_write_compute_decision(request, client)
    names = {name for name, _ in client.last_update_properties}
    assert SOURCE_LINK_PROPERTY not in names


# --- field allowlist -------------------------------------------------------------


def test_binding_outside_writable_logical_fields_is_rejected():
    request = _request(dry_run=True, compute_decision_binding=_binding(logical_field="source_link"))
    result = plan_and_write_compute_decision(request)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-field-not-allowlisted" in result.reason_codes


def test_binding_with_unsupported_property_type_is_rejected():
    request = _request(dry_run=True, compute_decision_binding=_binding(property_type="url"))
    result = plan_and_write_compute_decision(request)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-field-not-allowlisted" in result.reason_codes


def test_destination_mismatch_is_rejected():
    request = _request(dry_run=True, data_source_id="some-other-data-source")
    result = plan_and_write_compute_decision(request)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-destination-mismatch" in result.reason_codes


def test_schema_drift_blocks_before_any_mutation():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    drifted_schema = (
        NotionPropertySpec(COMPUTE_DECISION_PROPERTY, "select"),
        NotionPropertySpec(SOURCE_LINK_PROPERTY, "url"),
    )
    client = FakeNotionClient(pages=(page,), schema=drifted_schema)
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.PRECHECK_FAILED
    assert "notion-compute-decision-schema-property-type-drift" in result.reason_codes
    assert client.update_calls == 0


# --- ambiguous prior-write outcome: no blind retry ------------------------------


def test_ambiguous_update_outcome_reconciles_without_blind_retry_when_readback_matches():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = FakeNotionClient(
        pages=(page,), update_raises=NotionTransientError(), apply_write_before_raise=True
    )
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.UPDATED
    assert "notion-compute-decision-write-ambiguous-reconciled" in result.reason_codes
    assert client.update_calls == 1  # never blindly retried


def test_ambiguous_update_outcome_without_matching_readback_is_reported_ambiguous():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = FakeNotionClient(pages=(page,), update_raises=NotionRateLimitError(0.0))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.AMBIGUOUS_WRITE_RESULT
    assert "notion-compute-decision-update-outcome-ambiguous" in result.reason_codes
    assert client.update_calls == 1  # never blindly retried


# --- readback verification -------------------------------------------------------


class RevertingNotionClient(FakeNotionClient):
    """Applies an update but a subsequent readback shows the old value --
    e.g. the destination silently reverted the write."""

    def fetch_page(self, page_id):
        self.fetch_page_calls += 1
        page = self._pages.get(page_id)
        if page is None:
            return None
        return NotionTaskPageEvidence(page.page_id, page.source_link, "Do Not Spend Compute Yet")


def test_readback_mismatch_is_verification_failed():
    page = _page(compute_decision="Do Not Spend Compute Yet")
    client = RevertingNotionClient(pages=(page,))
    request = _request(dry_run=False, projection=_projection(disposition="run-now"))
    result = plan_and_write_compute_decision(request, client)
    assert result.state == WriteState.FAILED
    assert "notion-compute-decision-readback-mismatch" in result.reason_codes
    assert result.readback_verified is False


# --- determinism / no authority ---------------------------------------------------


def test_identical_input_produces_identical_plan():
    request = _request(dry_run=True, projection=_projection(disposition="focused-validation-first"))
    first = plan_and_write_compute_decision(request)
    second = plan_and_write_compute_decision(request)
    assert first == second


def test_no_authority_is_ever_created():
    request = _request(dry_run=True)
    result = plan_and_write_compute_decision(request)
    assert result.authority_created is False
