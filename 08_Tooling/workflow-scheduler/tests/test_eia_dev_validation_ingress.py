from __future__ import annotations

from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

REPOSITORY = "Blummer92/agent-os"
ACTOR = "Blummer92"
BRANCH = "agent/1768-eia-gce-host-projection"
SHA = "a" * 40
EIA_ID = "eia-paddleocr-runtime-qualification"


def _event(body: str) -> dict[str, object]:
    return {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 1768},
        "comment": {"id": 1, "body": body, "user": {"login": ACTOR}},
        "sender": {"login": ACTOR},
    }


def test_ingress_admits_only_the_canonical_eia_profile_identity() -> None:
    result = admit_issue_comment_event(
        _event(f"/agent-os dev-validate {BRANCH} {SHA} {EIA_ID}"),
        expected_repository=REPOSITORY,
        allowed_actor=ACTOR,
        run_attempt=1,
    )
    assert (result.status, result.reason) == ("accepted", "accepted-dev-validation-envelope")
    assert result.dev_validation_id_or_none == EIA_ID
    assert result.dev_validation_branch_or_none == BRANCH
    assert result.dev_validation_sha_or_none == SHA


def test_ingress_does_not_turn_eia_identity_into_command_surface() -> None:
    for suffix in (" --help", ";echo", "/extra"):
        result = admit_issue_comment_event(
            _event(f"/agent-os dev-validate {BRANCH} {SHA} {EIA_ID}{suffix}"),
            expected_repository=REPOSITORY,
            allowed_actor=ACTOR,
            run_attempt=1,
        )
        assert result.status == "ignored"
        assert result.reason == "malformed-trigger"
