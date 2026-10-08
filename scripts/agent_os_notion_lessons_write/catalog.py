"""Reviewed public working knowledge, never an authorization source.

Additional lessons require a deliberate repository change (a reviewed catalog
PR). Low-trust comments cannot supply content, properties, destinations, targets
or authorization booleans; they may only name a reviewed request id and, for an
update entry, bind the exact current revision of its reviewed target lesson.
"""
from types import MappingProxyType
import re

REQUEST_ID = "ckr6-execution-path-2026-10-05"
LL93_METADATA_REQUEST_ID = "ll-93-descriptive-metadata-2026-10-08"

# Narrative fields are required on every reviewed entry.
NARRATIVE_TYPES = MappingProxyType({
    "Lesson Learned": "title",
    "What Happened": "rich_text",
    "What To Do Next Time": "rich_text",
    "Guardrail": "rich_text",
})
# Owner decision D1 (#3417): reviewed entries MAY carry descriptive metadata.
# Descriptive metadata never activates a lesson.
DESCRIPTIVE_TYPES = MappingProxyType({
    "Area": "select",
    "Learning Type": "select",
    "Applies To": "multi_select",
    "Source Link": "url",
})
WRITABLE_TYPES = MappingProxyType({**NARRATIVE_TYPES, **DESCRIPTIVE_TYPES})
# Activation/readiness fields stay separately governed, per-action approved.
# No catalog entry may name them, and the writer never sends them.
PROTECTED_FIELDS = frozenset({"Status", "Surface Before Work?"})

MAX_TEXT = 512
MAX_APPLIES_TO = 8
SOURCE_LINK = re.compile(r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}")
LESSON_ID = re.compile(r"LL-([1-9][0-9]{0,8})")

# No readiness, approval, audit, owner, provenance-authority, relation or schema
# field is admitted, even if the existing integration could technically write it.
# An update entry names its reviewed target Lesson ID; a create entry has none.
LESSONS = MappingProxyType({
    REQUEST_ID: MappingProxyType({
        "target_lesson_id": None,
        "properties": MappingProxyType({
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
        }),
    }),
    # #3417/#3418 D1: descriptive classification for the existing LL-93 page.
    # Narrative is byte-identical to the canary entry; Status and Surface Before
    # Work? are deliberately absent, so executing this never activates LL-93.
    LL93_METADATA_REQUEST_ID: MappingProxyType({
        "target_lesson_id": "LL-93",
        "properties": MappingProxyType({
            "Area": "Governance",
            "Learning Type": "Mistake",
            "Applies To": ("Notion",),
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3305",
        }),
    }),
})


def _valid_value(name: str, value: object) -> bool:
    kind = WRITABLE_TYPES[name]
    if kind == "multi_select":
        return (type(value) is tuple and 0 < len(value) <= MAX_APPLIES_TO
                and len(set(value)) == len(value)
                and all(type(item) is str and item.strip() == item and 0 < len(item) <= 100
                        for item in value))
    if type(value) is not str or not value.strip() or len(value) > MAX_TEXT:
        return False
    if kind == "url":
        return SOURCE_LINK.fullmatch(value) is not None
    if kind == "select":
        return value.strip() == value and len(value) <= 100
    return True


def validate_entry(entry: object) -> MappingProxyType:
    """Fail closed unless the entry is a finite reviewed narrative (+ metadata)."""
    if not hasattr(entry, "keys") or set(entry) != {"target_lesson_id", "properties"}:
        raise ValueError("reviewed-entry-shape-required")
    target = entry["target_lesson_id"]
    if target is not None and (type(target) is not str or not LESSON_ID.fullmatch(target)):
        raise ValueError("reviewed-target-lesson-id-invalid")
    values = entry["properties"]
    if not hasattr(values, "keys"):
        raise ValueError("reviewed-narrative-fields-required")
    names = set(values)
    if names & PROTECTED_FIELDS:
        raise ValueError("protected-activation-field-refused")
    # A create entry carries the full narrative; a reviewed update entry may
    # change any nonempty subset of writable fields of its target lesson.
    required = set(NARRATIVE_TYPES) if target is None else set()
    if not names or not required <= names or not names <= set(WRITABLE_TYPES):
        raise ValueError("reviewed-narrative-fields-required")
    if any(not _valid_value(name, value) for name, value in values.items()):
        raise ValueError("reviewed-field-value-invalid")
    return entry


def entry_for(request_id: str) -> MappingProxyType:
    entry = LESSONS.get(request_id)
    if entry is None:
        raise ValueError("reviewed-request-unknown")
    return validate_entry(entry)


def lesson_for(request_id: str):
    """Select reviewed public fields only; catalog edits require review."""
    return entry_for(request_id)["properties"]


def target_for(request_id: str) -> str | None:
    return entry_for(request_id)["target_lesson_id"]
