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
CONTINUATION_CONSUMER_REQUEST_ID = "continuation-live-consumer-2026-10-30"

# Narrative fields are required on every reviewed entry.
NARRATIVE_TYPES = MappingProxyType({
    "Lesson Learned": "title",
    "What Happened": "rich_text",
    "What To Do Next Time": "rich_text",
    "Guardrail": "rich_text",
})
# Owner decision D1 (#3417): reviewed entries MAY carry descriptive metadata.
# Descriptive metadata never activates a lesson.
# #3973: "Supporting Source Links" is a bounded curated corroborating-ref
# field (rich_text, one canonical ref per item, max five). It is writable
# ONLY through a reviewed catalog entry + the existing guarded writer with
# exact-revision binding; it never activates a lesson, never substitutes
# for the primary Source Link, and never changes Status / Surface Before
# Work? (both stay in PROTECTED_FIELDS).
SUPPORTING_SOURCE_LINKS = "Supporting Source Links"
MAX_SUPPORTING_REFS = 5
DESCRIPTIVE_TYPES = MappingProxyType({
    "Area": "select",
    "Learning Type": "select",
    "Applies To": "multi_select",
    "Source Link": "url",
    SUPPORTING_SOURCE_LINKS: "rich_text",
})
WRITABLE_TYPES = MappingProxyType({**NARRATIVE_TYPES, **DESCRIPTIVE_TYPES})
# Activation/readiness fields stay separately governed, per-action approved.
# No catalog entry may name them, and the writer never sends them.
PROTECTED_FIELDS = frozenset({"Status", "Surface Before Work?"})

MAX_TEXT = 512
MAX_APPLIES_TO = 8
SOURCE_LINK = re.compile(r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]{0,6}")
GOVERNANCE_PREFIXES = (
    "00_Governance/",
    "01_Shared_Standards/",
    "02_Agent_Overlays/",
    "04_Registry/",
    "08_Tooling/",
)
LESSON_ID = re.compile(r"LL-([1-9][0-9]{0,8})")


def _valid_supporting_ref(value: str) -> bool:
    """One canonical supporting ref: this repo's issue/PR, or a governance path."""
    return len(value) <= MAX_TEXT and (
        SOURCE_LINK.fullmatch(value) is not None or value.startswith(GOVERNANCE_PREFIXES)
    )

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
    # #3690: reviewed continuation integration lesson, proposal only until
    # an owner-issued one-time #3417 command and exact Notion readback.
    CONTINUATION_CONSUMER_REQUEST_ID: MappingProxyType({
        "target_lesson_id": None,
        "properties": MappingProxyType({
            "Lesson Learned": "Connect continuation decisions to an actual host consumer before claiming automatic execution",
            "What Happened": (
                "Agent OS repaired continuation boundaries in merged PRs #2175 (Claude Stop hook), "
                "#2213 (MCP reachability), #2263 (false stall), #2494 (batch cursor), and "
                "#3670 (missing MCP payloads). Owner-reported Cloud Shell runs on "
                "2026-10-30 at main bb43fc08: 109 focused, 12 reconstructed, and "
                "30 MCP tests passed; QA did not independently reproduce those runs. "
                "Native host next-dispatch remains unverified. The approved five-tool "
                "chatgpt-governance profile excludes all continuation-named tools."
            ),
            "What To Do Next Time": (
                "Trace producer -> canonical payload -> registered MCP tool -> approved "
                "publication allowlist -> live host consumer -> next admitted dispatch -> "
                "exact receipt. Reuse existing driver, hooks and governed ingress; repair "
                "only the first proven disconnected boundary. Evaluate same-turn continuation "
                "and asynchronous post-stop re-entry as separate acceptance cases."
            ),
            "Guardrail": (
                "Registration, a green test, emitted agent_os_continuation or a successful "
                "same-turn read does not prove automatic host dispatch. Do not widen the "
                "five-tool allowlist without a separate owner decision or treat a Notion "
                "lesson as execution authority. Keep source/head, issue/PR lineage, "
                "currentness, bounded stops and no-duplicate-mutation checks explicit."
            ),
            "Area": "Governance",
            "Learning Type": "Mistake",
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3690",
        }),
    }),
    # Full-database repair 2026-11-14: 61 reviewed update entries.
    # Each entry carries the verified Source Link + Supporting Source
    # Links (0-5 distinct canonical refs) from WRITE_BATCH_61.csv.
    # Execution requires, per row, the owner command
    # `/agent-os notion-write <request-id> <LL-n> <exact-last-edited-time>`
    # on an ordinary GitHub issue (#3417 route). No entry names Status,
    # Surface Before Work?, Usage Count, or Recurrence Count.
    "ll-4-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-4",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/361",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/372",),
        }),
    }),
    "ll-5-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-5",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1325",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1328",),
        }),
    }),
    "ll-6-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-6",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/370",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/662",),
        }),
    }),
    "ll-9-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-9",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/358",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/414",),
        }),
    }),
    "ll-10-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-10",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/1366",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1364",),
        }),
    }),
    "ll-12-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-12",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1365",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1395", "https://github.com/Blummer92/agent-os/pull/1400"),
        }),
    }),
    "ll-13-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-13",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/903",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1220", "https://github.com/Blummer92/agent-os/pull/1225"),
        }),
    }),
    "ll-14-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-14",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1331",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/2005",),
        }),
    }),
    "ll-15-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-15",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/1366",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1364",),
        }),
    }),
    "ll-16-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-16",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/1366",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1364",),
        }),
    }),
    "ll-17-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-17",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/254",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/492", "https://github.com/Blummer92/agent-os/pull/495"),
        }),
    }),
    "ll-18-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-18",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/376",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/688", "https://github.com/Blummer92/agent-os/pull/558"),
        }),
    }),
    "ll-19-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-19",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1274",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1277",),
        }),
    }),
    "ll-23-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-23",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1365",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1395", "https://github.com/Blummer92/agent-os/pull/1400"),
        }),
    }),
    "ll-24-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-24",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1201",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1339",),
        }),
    }),
    "ll-25-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-25",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/723",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/728",),
        }),
    }),
    "ll-27-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-27",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/332",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/225",),
        }),
    }),
    "ll-30-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-30",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/307",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/316",),
        }),
    }),
    "ll-31-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-31",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1718",
        }),
    }),
    "ll-32-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-32",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1269",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1290",),
        }),
    }),
    "ll-33-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-33",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/358",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/414",),
        }),
    }),
    "ll-34-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-34",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1269",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1290", "https://github.com/Blummer92/agent-os/pull/2961"),
        }),
    }),
    "ll-35-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-35",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1269",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1290",),
        }),
    }),
    "ll-36-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-36",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1364",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1366",),
        }),
    }),
    "ll-37-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-37",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1364",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1366",),
        }),
    }),
    "ll-38-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-38",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1364",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1366",),
        }),
    }),
    "ll-40-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-40",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1364",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1366",),
        }),
    }),
    "ll-42-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-42",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1232",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1250",),
        }),
    }),
    "ll-45-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-45",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1232",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1250",),
        }),
    }),
    "ll-46-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-46",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/804",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/812",),
        }),
    }),
    "ll-47-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-47",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/357",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/405", "https://github.com/Blummer92/agent-os/pull/408"),
        }),
    }),
    "ll-48-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-48",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/357",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/405", "https://github.com/Blummer92/agent-os/pull/408"),
        }),
    }),
    "ll-49-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-49",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/538",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/539", "https://github.com/Blummer92/agent-os/pull/540"),
        }),
    }),
    "ll-50-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-50",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1138",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1350",),
        }),
    }),
    "ll-51-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-51",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1362",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1526", "https://github.com/Blummer92/agent-os/pull/1989"),
        }),
    }),
    "ll-52-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-52",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1614",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1615", "https://github.com/Blummer92/agent-os/pull/2409"),
        }),
    }),
    "ll-54-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-54",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1614",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1615", "https://github.com/Blummer92/agent-os/pull/2409"),
        }),
    }),
    "ll-55-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-55",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1602",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1635", "https://github.com/Blummer92/agent-os/pull/1725"),
        }),
    }),
    "ll-56-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-56",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1621",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1623",),
        }),
    }),
    "ll-57-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-57",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1608",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1609", "https://github.com/Blummer92/agent-os/pull/1633", "https://github.com/Blummer92/agent-os/pull/1662"),
        }),
    }),
    "ll-58-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-58",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1872",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1873",),
        }),
    }),
    "ll-61-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-61",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1865",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1866",),
        }),
    }),
    "ll-63-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-63",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1362",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1526", "https://github.com/Blummer92/agent-os/pull/1989"),
        }),
    }),
    "ll-64-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-64",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/2067",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/2080",),
        }),
    }),
    "ll-65-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-65",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1904",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1905",),
        }),
    }),
    "ll-66-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-66",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/229",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/230", "https://github.com/Blummer92/agent-os/pull/2961"),
        }),
    }),
    "ll-68-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-68",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1602",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1635", "https://github.com/Blummer92/agent-os/pull/1725"),
        }),
    }),
    "ll-69-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-69",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1985",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/2121", "https://github.com/Blummer92/agent-os/pull/2125", "https://github.com/Blummer92/agent-os/pull/2311"),
        }),
    }),
    "ll-72-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-72",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/2005",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1331",),
        }),
    }),
    "ll-73-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-73",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/2064",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/2077",),
        }),
    }),
    "ll-74-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-74",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/2220",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/2137", "https://github.com/Blummer92/agent-os/issues/2006"),
        }),
    }),
    "ll-75-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-75",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1362",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1526", "https://github.com/Blummer92/agent-os/pull/1989"),
        }),
    }),
    "ll-76-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-76",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1904",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1905",),
        }),
    }),
    "ll-79-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-79",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/229",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/230",),
        }),
    }),
    "ll-80-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-80",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1865",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/1866",),
        }),
    }),
    "ll-86-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-86",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3085",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/3312",),
        }),
    }),
    "ll-87-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-87",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3157",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/3164", "https://github.com/Blummer92/agent-os/pull/3161"),
        }),
    }),
    "ll-88-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-88",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3270",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/3271", "https://github.com/Blummer92/agent-os/pull/3267"),
        }),
    }),
    "ll-90-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-90",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/3303",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/3298",),
        }),
    }),
    "ll-91-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-91",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/3312",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/3085",),
        }),
    }),
    "ll-93-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-93",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/3305",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/pull/3358",),
        }),
    }),
    # Audit new repairs 2026-11-14 (D-A1--D-A4, NOT in the 61-row batch):
    # LL-21 primary #223; LL-62 primary #1251 + supporting #1873;
    # LL-82 primary #2220 + supporting #2230, #2093; LL-71 primary PR #1858
    # (D-A4 owner judgement call: candidate-grade primary) + supporting #1200.
    # LL-71's entry carries provenance only; the #3418 receipt recording
    # (D-A5/D-R1) is NOT included here and remains held out.
    "ll-21-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-21",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/223",
        }),
    }),
    "ll-62-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-62",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/1251",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1873",),
        }),
    }),
    "ll-82-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-82",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/issues/2220",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/2230", "https://github.com/Blummer92/agent-os/issues/2093"),
        }),
    }),
    "ll-71-source-and-supporting-2026-11-14": MappingProxyType({
        "target_lesson_id": "LL-71",
        "properties": MappingProxyType({
            "Source Link": "https://github.com/Blummer92/agent-os/pull/1858",
            "Supporting Source Links": ("https://github.com/Blummer92/agent-os/issues/1200",),
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
    if name == SUPPORTING_SOURCE_LINKS:
        return (type(value) is tuple and 0 < len(value) <= MAX_SUPPORTING_REFS
                and len(set(value)) == len(value)
                and all(type(item) is str and _valid_supporting_ref(item) for item in value))
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
