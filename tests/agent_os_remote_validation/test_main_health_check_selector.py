"""Regression tests for the #3461 main-health evidence-provenance selector.

Issue #3461: failed wrong-ref ``final-candidate`` workflow_dispatch runs
attached ``Run aggregate validation`` checks to the main SHA, and the
name+SHA+newest selection picked one of them as main-health evidence,
projecting ``main-health.infrastructure-unproven`` for unrelated PRs.

These tests pin the provenance filter: only ``push`` runs, and
``workflow_dispatch`` diagnostics issued by the validation workflow itself
(``github-actions[bot]``), bound to the exact main SHA, are authoritative
main-health evidence.
"""

from __future__ import annotations

import io
import json
import subprocess
from collections.abc import Mapping
from typing import Any
from unittest import mock

import pytest

from scripts.agent_os_remote_validation import main_health_check_selector as selector

MAIN_SHA = "851c98597d0040153fdfecc918b5880cc3232cfe"
OTHER_SHA = "637b05271e52d64172f2c541511f03297215653d"
REPO = "Blummer92/agent-os"

# Real incident chronology from #3461 (run ids are the actual ones).
POISONED_RUN_IDS = ("37844770925", "37844773898", "37844777451")
PUSH_RUN_ID = "37842913971"


def _check(
    run_id: str,
    *,
    status: str = "completed",
    conclusion: str | None = "failure",
    started_at: str = "2026-10-08T20:00:00Z",
    name: str = "Run aggregate validation",
    details_url: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "details_url": (
            details_url
            if details_url is not None
            else f"https://github.com/{REPO}/actions/runs/{run_id}/job/115137623902"
        ),
        "started_at": started_at,
        "completed_at": "2026-10-08T20:05:00Z",
    }


def _provenance(
    run_id: str,
    *,
    event: str = "workflow_dispatch",
    head_sha: str = MAIN_SHA,
    actor: str = "Blummer92",
) -> Mapping[str, Any]:
    return {"event": event, "head_sha": head_sha, "actor": actor}


def _resolver(mapping: Mapping[str, Mapping[str, Any] | None]):
    def resolve(run_id: str) -> Mapping[str, Any] | None:
        return mapping.get(run_id)

    return resolve


def test_rejects_wrong_ref_dispatch_checks_selects_push_success():
    """Exact #3461 chronology: three newer failed dispatches must not displace
    the older genuine push success on the same main SHA."""
    checks = [
        _check(POISONED_RUN_IDS[0], started_at="2026-10-08T20:10:00Z"),
        _check(POISONED_RUN_IDS[1], started_at="2026-10-08T20:11:00Z"),
        _check(POISONED_RUN_IDS[2], started_at="2026-10-08T20:12:00Z"),
        _check(
            PUSH_RUN_ID,
            conclusion="success",
            started_at="2026-10-08T19:00:00Z",
        ),
    ]
    provenance = {
        run_id: _provenance(run_id) for run_id in POISONED_RUN_IDS
    } | {PUSH_RUN_ID: _provenance(PUSH_RUN_ID, event="push")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert selected["conclusion"] == "success"
    assert PUSH_RUN_ID in str(selected["details_url"])


def test_latest_valid_main_success_beats_latest_invalid_dispatch_failure():
    checks = [
        _check("111", conclusion="failure", started_at="2026-10-08T21:00:00Z"),
        _check("222", conclusion="success", started_at="2026-10-08T20:00:00Z"),
    ]
    provenance = {
        "111": _provenance("111"),
        "222": _provenance("222", event="push"),
    }
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert selected["conclusion"] == "success"


def test_genuine_main_push_failure_is_not_hidden():
    """A failed push aggregate is authoritative: it must still be selected so
    main-health keeps rejecting a genuinely unhealthy main."""
    checks = [_check("333", conclusion="failure", started_at="2026-10-08T21:00:00Z")]
    provenance = {"333": _provenance("333", event="push")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert selected["conclusion"] == "failure"


def test_missing_evidence_returns_none():
    assert (
        selector.select_authoritative_check([], MAIN_SHA, _resolver({})) is None
    )


def test_no_authoritative_evidence_returns_none():
    checks = [_check("444", conclusion="failure")]
    provenance = {"444": _provenance("444")}  # human dispatch: not authoritative
    assert (
        selector.select_authoritative_check(checks, MAIN_SHA, _resolver(provenance))
        is None
    )


def test_delayed_in_flight_authoritative_check_is_selected():
    """#3351: an in-flight authoritative check is selected (the workflow's
    wait loop, not the selector, decides how long to wait for it)."""
    checks = [
        _check("555", status="in_progress", conclusion=None),
    ]
    provenance = {"555": _provenance("555", event="push")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert selected["status"] == "in_progress"


def test_stale_base_run_bound_to_other_sha_is_rejected():
    """A check whose run is bound to a different SHA is never main evidence,
    even when it is a push."""
    checks = [_check("666", conclusion="success")]
    provenance = {"666": _provenance("666", event="push", head_sha=OTHER_SHA)}
    assert (
        selector.select_authoritative_check(checks, MAIN_SHA, _resolver(provenance))
        is None
    )


def test_human_dispatched_success_is_rejected_fail_closed():
    """A manually dispatched diagnostic that succeeded is still ambiguous
    provenance: excluded, keeping fail-closed behavior."""
    checks = [_check("777", conclusion="success")]
    provenance = {"777": _provenance("777", actor="Blummer92")}
    assert (
        selector.select_authoritative_check(checks, MAIN_SHA, _resolver(provenance))
        is None
    )


def test_sanctioned_bot_diagnostic_dispatch_is_selected():
    """The workflow's own recovery dispatch (github-actions[bot]) is approved
    diagnostic validation and must remain selectable."""
    checks = [_check("888", conclusion="success")]
    provenance = {"888": _provenance("888", actor="github-actions[bot]")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert selected["conclusion"] == "success"


def test_bot_dispatch_bound_to_other_sha_is_rejected():
    checks = [_check("889", conclusion="success")]
    provenance = {
        "889": _provenance("889", actor="github-actions[bot]", head_sha=OTHER_SHA)
    }
    assert (
        selector.select_authoritative_check(checks, MAIN_SHA, _resolver(provenance))
        is None
    )


def test_unresolvable_details_url_is_skipped():
    checks = [
        _check("999", conclusion="success", details_url="not-a-url"),
        _check("222", conclusion="success", started_at="2026-10-08T20:00:00Z"),
    ]
    provenance = {"222": _provenance("222", event="push")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert "222" in str(selected["details_url"])


def test_run_api_failure_skips_candidate_but_keeps_others():
    def resolve(run_id: str):
        if run_id == "101":
            return None  # gh api failed for this run
        return _provenance(run_id, event="push")

    checks = [
        _check("101", conclusion="success", started_at="2026-10-08T22:00:00Z"),
        _check("202", conclusion="success", started_at="2026-10-08T21:00:00Z"),
    ]
    selected = selector.select_authoritative_check(checks, MAIN_SHA, resolve)
    assert selected is not None
    assert "202" in str(selected["details_url"])


def test_newest_authoritative_check_wins():
    checks = [
        _check("301", conclusion="success", started_at="2026-10-08T20:00:00Z"),
        _check("302", conclusion="success", started_at="2026-10-08T21:00:00Z"),
    ]
    provenance = {
        "301": _provenance("301", event="push"),
        "302": _provenance("302", event="push"),
    }
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert "302" in str(selected["details_url"])


def test_other_check_names_are_ignored():
    checks = [
        _check("401", conclusion="failure", name="Some other check"),
        _check("402", conclusion="success"),
    ]
    provenance = {
        "401": _provenance("401", event="push"),
        "402": _provenance("402", event="push"),
    }
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert "402" in str(selected["details_url"])


def test_output_shape_matches_workflow_contract():
    """The workflow consumes {status, conclusion, details_url, started_at,
    completed_at} — exactly what the old inline jq produced."""
    checks = [_check("501", conclusion="success")]
    provenance = {"501": _provenance("501", event="push")}
    selected = selector.select_authoritative_check(
        checks, MAIN_SHA, _resolver(provenance)
    )
    assert selected is not None
    assert set(selected.keys()) == {
        "status",
        "conclusion",
        "details_url",
        "started_at",
        "completed_at",
    }


def test_extract_run_id():
    assert (
        selector.extract_run_id(
            f"https://github.com/{REPO}/actions/runs/37844777451/job/115137623902"
        )
        == "37844777451"
    )
    assert selector.extract_run_id(None) is None
    assert selector.extract_run_id("https://example.com/no-run-here") is None


def _run_main(
    payload: dict[str, Any],
    argv: list[str],
    env: dict[str, str],
    gh_responses: Mapping[str, str] | None = None,
) -> tuple[int, str, str]:
    stdin = io.StringIO(json.dumps(payload))

    def fake_run(cmd, **kwargs):
        run_id = cmd[2].split("/actions/runs/")[1]
        body = (gh_responses or {}).get(run_id, '{"event":"push"}')
        return subprocess.CompletedProcess(cmd, 0, body, "")

    with (
        mock.patch.object(selector.sys, "stdin", stdin),
        mock.patch.dict(selector.os.environ, env, clear=False),
        mock.patch.object(selector.subprocess, "run", side_effect=fake_run),
        mock.patch.object(selector.sys, "stdout", new_callable=io.StringIO) as out,
        mock.patch.object(selector.sys, "stderr", new_callable=io.StringIO) as err,
    ):
        code = selector.main(argv)
    return code, out.getvalue(), err.getvalue()


def test_main_selects_authoritative_check_end_to_end():
    payload = {
        "check_runs": [
            _check("601", conclusion="failure", started_at="2026-10-08T21:00:00Z"),
            _check("602", conclusion="success", started_at="2026-10-08T20:00:00Z"),
        ]
    }
    code, out, _ = _run_main(
        payload,
        [],
        {"MAIN_HEALTH_SHA": MAIN_SHA, "GITHUB_REPOSITORY": REPO},
        {
            "601": json.dumps(
                {"event": "workflow_dispatch", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            ),
            "602": json.dumps(
                {"event": "push", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            ),
        },
    )
    assert code == 0
    selected = json.loads(out)
    assert selected["conclusion"] == "success"
    assert "602" in selected["details_url"]


def test_main_reports_empty_object_when_nothing_authoritative():
    payload = {"check_runs": [_check("603", conclusion="failure")]}
    code, out, _ = _run_main(
        payload,
        [],
        {"MAIN_HEALTH_SHA": MAIN_SHA, "GITHUB_REPOSITORY": REPO},
        {
            "603": json.dumps(
                {"event": "workflow_dispatch", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            )
        },
    )
    assert code == 0
    assert json.loads(out) == {}


def test_main_count_mode_counts_authoritative_only():
    payload = {
        "check_runs": [
            _check("604", conclusion="failure"),
            _check("605", conclusion="success"),
            _check("606", conclusion="success"),
        ]
    }
    code, out, _ = _run_main(
        payload,
        ["--count"],
        {"MAIN_HEALTH_SHA": MAIN_SHA, "GITHUB_REPOSITORY": REPO},
        {
            "604": json.dumps(
                {"event": "workflow_dispatch", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            ),
            "605": json.dumps(
                {"event": "push", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            ),
            "606": json.dumps(
                {"event": "push", "head_sha": MAIN_SHA, "actor": "Blummer92"}
            ),
        },
    )
    assert code == 0
    assert out.strip() == "2"


def test_main_rejects_malformed_stdin():
    with (
        mock.patch.object(selector.sys, "stdin", io.StringIO("not json")),
        mock.patch.object(selector.sys, "stdout", new_callable=io.StringIO),
        mock.patch.object(selector.sys, "stderr", new_callable=io.StringIO),
    ):
        assert selector.main([]) == 2
