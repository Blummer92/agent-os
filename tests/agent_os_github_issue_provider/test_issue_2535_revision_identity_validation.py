import pytest

from scripts.agent_os_github_issue_provider.revision import canonical_issue_payload


def _issue(**overrides: object) -> dict[str, object]:
    issue: dict[str, object] = {
        "number": 2535,
        "title": "Bug",
        "state": "open",
        "body": "body",
        "html_url": "https://github.com/Blummer92/agent-os/issues/2535",
        "created_at": "2026-09-16T20:00:00Z",
        "updated_at": "2026-09-16T20:00:00Z",
        "labels": ["type:bug"],
    }
    issue.update(overrides)
    return issue


def test_valid_issue_identity_is_accepted() -> None:
    assert canonical_issue_payload(_issue())


@pytest.mark.parametrize("number", (True, 0, -1))
def test_invalid_issue_number_fails_closed(number: object) -> None:
    with pytest.raises(ValueError, match="issue number must be a positive integer"):
        canonical_issue_payload(_issue(number=number))


def test_unsupported_issue_state_fails_closed() -> None:
    with pytest.raises(ValueError, match="issue state must be open or closed"):
        canonical_issue_payload(_issue(state="banana"))
