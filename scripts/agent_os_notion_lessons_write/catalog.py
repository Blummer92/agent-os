"""Reviewed public working knowledge, never an authorization source.

Additional lessons require a deliberate repository change. Low-trust comments
cannot supply content, properties, destinations, or authorization booleans.
"""
from types import MappingProxyType

REQUEST_ID = "ckr6-execution-path-2026-10-05"
ISSUE_NUMBER = 3305
TASK_OWNER = "ChatGPT Orchestrator"
EXECUTOR = "GitHub Service Agent"
AUTHORIZATION_POLICY = "00_Governance/write-authorization-policy.md"
WRITABLE_TYPES = MappingProxyType({
    "Lesson Learned": "title",
    "What Happened": "rich_text",
    "What To Do Next Time": "rich_text",
    "Guardrail": "rich_text",
})
# Every value is bounded, reviewed, non-sensitive Agent OS working knowledge.
# No readiness, approval, audit, owner, provenance-authority, relation or schema
# field is admitted, even if the existing integration could technically write it.
LESSONS = MappingProxyType({REQUEST_ID: MappingProxyType({
    "Lesson Learned": "CKR6 must run in the actual execution path",
    "What Happened": (
        "On 2026-10-05, the repository owner requested that the CKR6 lesson "
        "be saved. The GitHub-controlled Notion route could read working "
        "knowledge but had no authorized Lessons Learned write executor. "
        "Documenting CKR6 alone did not prove that live execution consumed it."
    ),
    "What To Do Next Time": (
        "Before substantial Agent OS work, follow request -> CKR6 materiality "
        "-> relevant Lessons Learned -> execution decision. After a failed "
        "repair, re-enter the canonical retry-specific CKR6 contract before "
        "forming another repair hypothesis. Verify the actual execution path."
    ),
    "Guardrail": (
        "Lessons remain advisory working knowledge. Current GitHub governance, "
        "authorization, code, tests and exact-head evidence remain authoritative. "
        "Never claim a lesson was persisted without canonical Notion readback."
    ),
})})


def lesson_for(request_id: str):
    """Select reviewed public narrative only; catalog edits require review."""
    lesson = LESSONS.get(request_id)
    if lesson is None or set(lesson) != set(WRITABLE_TYPES) or any(
        type(value) is not str or not value.strip() or len(value) > 512
        for value in lesson.values()
    ):
        raise ValueError("reviewed-narrative-fields-required")
    return lesson
