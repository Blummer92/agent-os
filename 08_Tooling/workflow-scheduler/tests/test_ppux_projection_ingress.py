"""Ingress admission for the fixed PPUX prompt-projection trigger (#2673).

``/agent-os project-ppux-prompts <branch> <sha40> <input-ref-64hex>`` admits
the accepted-ppux-projection-envelope selector identity with the exact
branch/SHA/input-ref. It never authorizes execution, and the existing
ppux-picture-perfect-ts-vitest dev-validate trigger is unchanged.
"""
from __future__ import annotations

import pytest

from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
BRANCH = "agent/2673-ppux-projection-transport"
SHA = "a" * 40
INPUT_REF = "b" * 64
TRIGGER = f"/agent-os project-ppux-prompts {BRANCH} {SHA} {INPUT_REF}"
DEV_SHA = "c" * 40
DEV_TRIGGER = f"/agent-os dev-validate agent/1271-validation-profile-path-coverage {DEV_SHA} remote-validation-suite"


def event(body: str) -> dict[str, object]:
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2673},
        "comment": {"id": 4001, "body": body, "user": {"login": ACTOR}},
        "sender": {"login": ACTOR},
    }


def admit(payload: object):
    return admit_issue_comment_event(
        payload,
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=1,
    )


def test_projection_trigger_accepts_with_exact_identities() -> None:
    result = admit(event(TRIGGER))

    assert result.status == "accepted"
    assert result.reason == "accepted-ppux-projection-envelope"
    assert result.ppux_projection_branch_or_none == BRANCH
    assert result.ppux_projection_sha_or_none == SHA
    assert result.ppux_projection_input_ref_or_none == INPUT_REF
    assert result.logical_trigger_id_or_none is not None
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False


def test_projection_trigger_identities_survive_to_dict_round_trip() -> None:
    result = admit(event(TRIGGER))
    payload = result.to_dict()

    assert payload["ppux_projection_branch_or_none"] == BRANCH
    assert payload["ppux_projection_sha_or_none"] == SHA
    assert payload["ppux_projection_input_ref_or_none"] == INPUT_REF
    assert payload["reason"] == "accepted-ppux-projection-envelope"


@pytest.mark.parametrize(
    "body",
    [
        # wrong SHA lengths
        f"/agent-os project-ppux-prompts {BRANCH} {'a' * 39} {INPUT_REF}",
        f"/agent-os project-ppux-prompts {BRANCH} {'a' * 41} {INPUT_REF}",
        f"/agent-os project-ppux-prompts {BRANCH} {'A' * 40} {INPUT_REF}",
        # wrong input-ref lengths
        f"/agent-os project-ppux-prompts {BRANCH} {SHA} {'b' * 63}",
        f"/agent-os project-ppux-prompts {BRANCH} {SHA} {'b' * 65}",
        f"/agent-os project-ppux-prompts {BRANCH} {SHA} {'B' * 64}",
        # non-agent branch
        f"/agent-os project-ppux-prompts main {SHA} {INPUT_REF}",
        f"/agent-os project-ppux-prompts feature/x {SHA} {INPUT_REF}",
        # extra / missing tokens
        f"/agent-os project-ppux-prompts {BRANCH} {SHA}",
        f"/agent-os project-ppux-prompts {BRANCH} {SHA} {INPUT_REF} extra",
        f"/agent-os project-ppux-prompts  {SHA} {INPUT_REF}",
        # empty body
        "",
    ],
)
def test_malformed_projection_triggers_are_ignored(body: str) -> None:
    result = admit(event(body))

    assert (result.status, result.reason) == ("ignored", "malformed-trigger")
    assert result.ppux_projection_branch_or_none is None
    assert result.ppux_projection_sha_or_none is None
    assert result.ppux_projection_input_ref_or_none is None


def test_branch_injection_attempts_are_ignored() -> None:
    result = admit(event(f"/agent-os project-ppux-prompts agent/x;rm -rf / {SHA} {INPUT_REF}"))
    assert result.status == "ignored"
    result = admit(event(f"/agent-os project-ppux-prompts agent/x`id` {SHA} {INPUT_REF}"))
    assert result.status == "ignored"
    result = admit(event(f"/agent-os project-ppux-prompts agent/x$(id) {SHA} {INPUT_REF}"))
    assert result.status == "ignored"


def test_projection_trigger_does_not_match_other_selectors() -> None:
    result = admit(event(TRIGGER))

    assert result.dev_validation_branch_or_none is None
    assert result.handoff_id_or_none is None
    assert result.source_capsule_id_or_none is None


def test_ppux_vitest_dev_validate_trigger_still_accepted() -> None:
    result = admit(event("/agent-os dev-validate agent/1271-validation-profile-path-coverage " + DEV_SHA + " ppux-picture-perfect-ts-vitest"))

    assert result.status == "accepted"
    assert result.reason == "accepted-dev-validation-envelope"
    assert result.dev_validation_id_or_none == "ppux-picture-perfect-ts-vitest"
    assert result.ppux_projection_branch_or_none is None


def test_dev_validate_trigger_still_accepted() -> None:
    result = admit(event(DEV_TRIGGER))

    assert result.status == "accepted"
    assert result.reason == "accepted-dev-validation-envelope"
    assert result.ppux_projection_branch_or_none is None
