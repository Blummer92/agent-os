"""PR3750 S02/S03/S04: knowledge must not overstate host execution."""
from scripts.agent_os_notion_lessons_write.catalog import (
    CONTINUATION_CONSUMER_REQUEST_ID, lesson_for,
)


def test_pr3750_guardrail_cannot_invert_owner_allowlist_decision():
    values = lesson_for(CONTINUATION_CONSUMER_REQUEST_ID)
    assert "Do not widen the five-tool allowlist without a separate owner decision" in values["Guardrail"]


def test_pr3750_host_next_dispatch_stays_explicitly_unverified():
    values = lesson_for(CONTINUATION_CONSUMER_REQUEST_ID)
    assert "Native host next-dispatch remains unverified." in values["What Happened"]


def test_pr3750_lesson_title_is_exact_dedupe_identity():
    values = lesson_for(CONTINUATION_CONSUMER_REQUEST_ID)
    assert values["Lesson Learned"] == (
        "Connect continuation decisions to an actual host consumer before claiming automatic execution"
    )
