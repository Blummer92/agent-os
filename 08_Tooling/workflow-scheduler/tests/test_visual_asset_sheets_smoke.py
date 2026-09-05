from dataclasses import replace

import pytest

from workflow_scheduler.governance.visual_asset_sheets_smoke import (
    REQUIRED_SCOPE,
    build_request,
    execute_smoke,
)

SHA = "a" * 40
SHEET = "1S3GNwqu0ehPXUA1j4FEksH1uEMKlxyEwAZWfIADPfpo"
RANGE = "'Approved Use Review'!A1:N455"


def request():
    return build_request(
        repository="Blummer92/agent-os",
        issue_number=734,
        source_sha=SHA,
        spreadsheet_id=SHEET,
        worksheet_name="Approved Use Review",
        a1_range=RANGE,
    )


def test_request_is_content_bound_to_target_and_source_revision():
    original = request()
    changed = build_request(
        repository=original.repository,
        issue_number=734,
        source_sha="b" * 40,
        spreadsheet_id=SHEET,
        worksheet_name="Approved Use Review",
        a1_range=RANGE,
    )
    assert original.request_id != changed.request_id
    with pytest.raises(ValueError, match="identity drift"):
        execute_smoke(replace(original, request_id=changed.request_id), inspect_effective_scopes=lambda: [REQUIRED_SCOPE], values_get=lambda *_: {"values": []})


def test_exact_scope_allows_one_bounded_read_and_emits_no_rows():
    calls = []
    evidence = execute_smoke(
        request(),
        inspect_effective_scopes=lambda: [REQUIRED_SCOPE],
        values_get=lambda sheet, a1: calls.append((sheet, a1)) or {"values": [["header"], ["private"]]},
    )
    assert calls == [(SHEET, RANGE)]
    assert evidence["status"] == "success"
    assert evidence["scope_verified"] is True
    assert evidence["response_row_count"] == 2
    assert "values" not in evidence
    assert evidence["external_write_performed"] is False
    assert evidence["credential_material_emitted"] is False


def test_broader_scope_fails_before_api_call():
    calls = []
    evidence = execute_smoke(
        request(),
        inspect_effective_scopes=lambda: [REQUIRED_SCOPE, "https://www.googleapis.com/auth/drive.readonly"],
        values_get=lambda *_: calls.append(True) or {"values": []},
    )
    assert calls == []
    assert evidence["status"] == "blocked"
    assert evidence["reason_codes"] == ["scope-not-least-privilege"]


def test_unverifiable_scope_fails_before_api_call():
    calls = []
    evidence = execute_smoke(
        request(),
        inspect_effective_scopes=lambda: None,
        values_get=lambda *_: calls.append(True) or {"values": []},
    )
    assert calls == []
    assert evidence["reason_codes"] == ["scope-unverifiable"]


def test_malformed_or_oversized_response_fails_closed_without_raw_data():
    evidence = execute_smoke(
        request(),
        inspect_effective_scopes=lambda: REQUIRED_SCOPE,
        values_get=lambda *_: {"values": [[] for _ in range(456)]},
    )
    assert evidence["status"] == "blocked"
    assert evidence["reason_codes"] == ["sheets-response-malformed"]
    assert "values" not in evidence


def test_request_rejects_target_range_drift():
    with pytest.raises(ValueError, match="invalid bounded a1 range"):
        build_request(
            repository="Blummer92/agent-os",
            issue_number=734,
            source_sha=SHA,
            spreadsheet_id=SHEET,
            worksheet_name="Approved Use Review",
            a1_range="'Different Tab'!A1:N455",
        )


def test_request_rejects_other_consumer_issue():
    with pytest.raises(ValueError, match="consumer issue"):
        build_request(
            repository="Blummer92/agent-os",
            issue_number=735,
            source_sha=SHA,
            spreadsheet_id=SHEET,
            worksheet_name="Approved Use Review",
            a1_range=RANGE,
        )
