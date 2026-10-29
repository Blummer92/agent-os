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
LL87_GUARDRAIL_REQUEST_ID = "ll-87-guardrail-refinement-2026-10-10"
TEST_DETECTION_REQUEST_ID = "ll-new-test-detection-proof-2026-10-29"
MERGE_ACCEPTANCE_REQUEST_ID = "ll-new-merge-is-not-acceptance-2026-10-29"
LL10_FIXTURE_REQUEST_ID = "ll-10-single-fault-fixtures-2026-10-29"
LL18_METRIC_REQUEST_ID = "ll-18-metric-integrity-2026-10-29"

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
    # #3418 Test G: reviewed narrative-only LL-87 update from CKR6 receipt 6096274166.
    # The owner must separately bind the live last_edited_time at execution.
    LL87_GUARDRAIL_REQUEST_ID: MappingProxyType({
        "target_lesson_id": "LL-87",
        "properties": MappingProxyType({
            "Guardrail": "If a PR description contains a GitHub closing keyword referencing an issue, merging may close that issue. When live acceptance remains, use a non-closing Part of reference and verify the PR description before merge.",
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
    # #3418 October 29 evidence campaign; reviewed proposals, inert until owner write.
    TEST_DETECTION_REQUEST_ID: MappingProxyType({
        "target_lesson_id": None,
        "properties": MappingProxyType({
            "Lesson Learned": "A passing or mapped test is not proof it detects the protected regression",
            "What Happened": "Oct 28-29 2026 mutation runs: M07 and M10 in parse_pr.py survived the 76-test #3506 file that exercised both functions; PR #3742 added 7 cases that kill each (3 failures). On main bb43fc08, removing timed_out, cancelled and action_required from validation-currentness failure conclusions, or letting the oldest duplicate check run win in merge applicability, still passed every collected test in tests/agent_os_issue_acceptance and tests/agent_os_remote_validation.",
            "What To Do Next Time": "For each guard you add or change, write a single-fault case that asserts its exact reason code. Then remove the guard and confirm that named test fails at the exact SHA; record mutant, SHA and killing test. Classify each mutant: killed, survived, downstream-guarded, or unverified. Treat coverage, static links and duplicate-looking tests as candidates; never delete one without comparing unique detection.",
            "Guardrail": "Test execution, coverage, static test links and green CI never prove detection. Call a guard protected only when a recorded test fails for its mutant at the exact SHA. A downstream safeguard does not close a gap at the producer boundary.",
            "Area": "Testing",
            "Learning Type": "Testing lesson",
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3506",
        }),
    }),
    # #3418 October 29 evidence campaign; reviewed proposals, inert until owner write.
    MERGE_ACCEPTANCE_REQUEST_ID: MappingProxyType({
        "target_lesson_id": None,
        "properties": MappingProxyType({
            "Lesson Learned": "A merged PR with green CI is delivery evidence, not acceptance",
            "What Happened": "Oct 2026: PRs #3693, #3742, #3728, #3739, #3737, #3738 and #3723 merged with exact-head aggregate PASS while their issues stayed open for a live receipt, post-merge mutant rerun, closure canary or acceptance admission. Before PR #3708 (57cedc86, merged 2026-10-22), report-only Issue Acceptance jobs, e.g. on #3511, #3703, #3671 and #3658, logged 'Overall result: fail' then exited 0, so the check showed green while its verdict was FAIL.",
            "What To Do Next Time": "Track each acceptance criterion with its own evidence: code merged, exact-head CI, independent QA at the final head, post-merge or live execution, and authorized closure. Read the checker verdict, not the job colour; WARN and MANUAL_REVIEW exit 0 by design. Keep the issue open and name the missing evidence. An open issue alone does not mean the fix failed.",
            "Guardrail": "Never report an issue accepted or fixed because its PR merged or a report-only job is green. Each criterion without its own evidence stays NOT_VERIFIED.",
            "Area": "Governance",
            "Learning Type": "Mistake",
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3691",
        }),
    }),
    # #3418 October 29 evidence campaign; reviewed proposals, inert until owner write.
    LL10_FIXTURE_REQUEST_ID: MappingProxyType({
        "target_lesson_id": "LL-10",
        "properties": MappingProxyType({
            "What To Do Next Time": "Define the adversarial matrix before implementation and make ambiguity, contradictions, malformed or oversized inputs, distinct-but-similar cases, and no-change outcomes first-class fixtures. Treat the happy path as only one case in the contract. Give every guard one single-fault case that asserts its exact reason code, and cover each terminal value the code branches on, such as timed_out, cancelled and action_required.",
            "Guardrail": "Characterize current behavior and protect failure, ambiguity, boundedness, and no-side-effect paths with deterministic fixtures before changing automation behavior. Multi-fault cases and prefix-only assertions cannot show which guard fired, so they hide guard removal.",
        }),
    }),
    # #3418 October 29 evidence campaign; reviewed proposals, inert until owner write.
    LL18_METRIC_REQUEST_ID: MappingProxyType({
        "target_lesson_id": "LL-18",
        "properties": MappingProxyType({
            "What To Do Next Time": "Bind completeness to the requested scope, pagination state, repository identity, and exact revision. Require positive terminal pagination proof; incomplete, unknown, moved, or partial retrieval must remain explicit and fail closed/manual review. Before using a count or rate, check that the stated total equals its listed parts under one population definition and that the sample is representative.",
            "Guardrail": "One valid page is not a complete scan. Never promote partial or unknown pagination evidence to complete repository state. A total that disagrees with its parts, or mixes event types under one label, stays manual review and is not decision evidence.",
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
