"""PR3750 S02/S03/S04 + #3417 LL-82 refinement: knowledge must not overstate host execution."""
from scripts.agent_os_notion_lessons_write.catalog import (
    LL82_CONTINUATION_REFINEMENT_REQUEST_ID, lesson_for,
)


def test_ll82_guardrail_cannot_claim_host_dispatch_from_emission():
    values = lesson_for(LL82_CONTINUATION_REFINEMENT_REQUEST_ID)
    assert "PR #3670 proves payload emission, not host next-dispatch" in values["Guardrail"]


def test_ll82_host_next_dispatch_stays_explicitly_unverified():
    values = lesson_for(LL82_CONTINUATION_REFINEMENT_REQUEST_ID)
    assert "next-operation dispatch remain unverified" in values["What Happened"]


def test_ll82_lesson_title_preserves_stable_identity():
    values = lesson_for(LL82_CONTINUATION_REFINEMENT_REQUEST_ID)
    assert values["Lesson Learned"] == (
        "Native execution hosts must enforce continuation; emitted continuation metadata alone is insufficient"
    )
