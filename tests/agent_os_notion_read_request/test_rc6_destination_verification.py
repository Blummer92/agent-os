"""#2871 fixed RC6 destination verification regressions."""

from __future__ import annotations

from scripts.agent_os_notion_read_request import load_catalog, run_notion_read_request

from .notion_read_support import ACTOR, GENERATED_AT, REPOSITORY, RecordingExecutor, transport

REQUEST_ID = "rc6-operator-planning-destination"
PAGE_ID = "3a57ac78313181068440df5a7fc9ae85"
EXPECTED_TITLE = "Agent OS / RC6 Participant Pilot / Operator Planning and Readiness"


def rc6_transport(**overrides):
    issue_number = overrides.pop("issue_number", 249)
    return transport(request_id=REQUEST_ID, issue_number=issue_number, **overrides)


def rc6_executor(*, title=EXPECTED_TITLE, public_url=None, page_id=PAGE_ID):
    return RecordingExecutor(
        page_id=page_id,
        page={
            "id": page_id,
            "title": title,
            "url": "https://www.notion.so/private-page-location",
            "public_url": public_url,
            "archived": False,
            "in_trash": False,
            "last_edited_time": "2026-09-23T14:00:00.000Z",
        },
    )


def run(executor, payload=None):
    return run_notion_read_request(
        payload or rc6_transport(),
        expected_repository=REPOSITORY,
        expected_actor=ACTOR,
        generated_at=GENERATED_AT,
        catalog=load_catalog(),
        scheduler_task_executor_factory=executor.factory,
    )


def test_fixed_rc6_request_reads_only_the_registered_page():
    executor = rc6_executor()
    evidence = run(executor)

    assert executor.calls == [{"action": "get_page", "page_id": PAGE_ID}]
    assert evidence["dispatch_status"] == "completed"
    result = evidence["result"]
    assert result["request_id"] == REQUEST_ID
    assert result["destination_id"] == PAGE_ID
    assert result["expected_title"] == EXPECTED_TITLE
    assert result["observed_title"] == EXPECTED_TITLE
    assert result["title_matches"] is True
    assert result["reachable"] is True
    assert result["public_url_present"] is False
    assert result["sharing_evidence_scope"] == "public-url-only"
    assert result["write_allowed"] is False
    assert result["production_authorized"] is False
    assert "private-page-location" not in repr(result)


def test_live_dashed_notion_page_id_matches_registered_undashed_binding():
    live_page_id = "3a57ac78-3131-8106-8440-df5a7fc9ae85"
    executor = rc6_executor(page_id=live_page_id)

    evidence = run(executor)

    assert executor.calls == [{"action": "get_page", "page_id": PAGE_ID}]
    assert evidence["dispatch_status"] == "completed"
    assert evidence["result"]["destination_id"] == PAGE_ID


def test_wrong_issue_cannot_dispatch_fixed_destination():
    evidence = run(rc6_executor(), rc6_transport(issue_number=2283))
    assert evidence["dispatch_status"] == "blocked"
    assert evidence["admission"]["reason_codes"] == ["issue-target-mismatch"]


def test_caller_cannot_supply_page_id_or_url():
    evidence = run(
        rc6_executor(),
        rc6_transport(page_id="attacker-page", url="https://notion.so/attacker"),
    )
    # Extra transport fields never influence the repository-owned fixed binding.
    assert evidence["result"]["destination_id"] == PAGE_ID


def test_title_mismatch_is_visible_not_silently_accepted():
    evidence = run(rc6_executor(title="Different destination"))
    assert evidence["result"]["title_matches"] is False


def test_public_url_presence_is_visible_without_publishing_the_url():
    evidence = run(rc6_executor(public_url="https://notion.site/public-secret-slug"))
    result = evidence["result"]
    assert result["public_url_present"] is True
    assert "public-secret-slug" not in repr(result)
