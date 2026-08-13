"""Contract tests for the canonical Agent Interaction Output Standard (#926).

These fixtures verify that one shared standard owns the interaction-output
contract, that former schema surfaces are compatibility pointers rather than
competing policy sources, and that the ten required presentation profiles keep
predictable visible ordering plus machine-checkable summary compatibility.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"
FINAL_REPORT = ROOT / "01_Shared_Standards/global-engineering/final-report-standard.md"
GLOBAL_README = ROOT / "01_Shared_Standards/global-engineering/README.md"
COMMON_OVERLAY = ROOT / "02_Agent_Overlays/_common-overlay-rules.md"
ORCHESTRATOR = ROOT / "02_Agent_Overlays/chatgpt-orchestrator.md"
AGENTS = ROOT / "AGENTS.md"
OUTPUT_SCHEMA = ROOT / "07_Agent_Tests/agent-output-schema.md"
TEST_CHECKLIST = ROOT / "07_Agent_Tests/common-test-checklist.md"
PROFILE_MATRIX = ROOT / "07_Agent_Tests/interaction-output-profile-matrix.md"
ORCHESTRATOR_TESTS = ROOT / "07_Agent_Tests/chatgpt-orchestrator.tests.md"
VERSION_MAP = ROOT / "04_Registry/module-version-map.md"
NAVIGATION = ROOT / "04_Registry/navigation-alias-registry.md"
ARTIFACT_FIRST = ROOT / "01_Shared_Standards/instructional-design/artifact-first-response-standard.md"
TEACHER_STUDIO = ROOT / "01_Shared_Standards/instructional-design/teacher-decision-studio-standard.md"

CANONICAL_PATH = "01_Shared_Standards/global-engineering/agent-interaction-output-standard.md"

BASE_FIELDS = (
    "status",
    "blockers",
    "checks_passed",
    "checks_failed",
    "next_owner",
    "handoff_artifacts",
    "files_changed",
    "tests_run",
    "docs_updated",
    "remaining_risks",
)

ROUTING_FIELDS = (
    "task_owner",
    "selected_overlay",
    "standards_read",
    "allowed_actions",
    "blocked_actions",
    "context_packet",
    "stop_conditions",
)

GITHUB_FIELDS = (
    "repository",
    "issue",
    "branch",
    "pull request",
    "exact head",
    "validation state",
    "current stage",
    "next action",
)

# profile label -> phrases that must appear in its "lead with" cell
PROFILE_ORDERING = {
    "Simple status": ("the direct answer",),
    "GitHub read-only investigation": (
        "verified status or blocker",
        "smallest next action",
    ),
    "Issue implementation": (
        "completed, current, remaining, blockers",
        "execution route",
        "next action",
    ),
    "PR review or terminal handoff": ("exact-head evidence", "handoff"),
    "Blocked work": ("controlling blocker", "exact unblock condition"),
    "Prompt or command delivery": ("one reusable copy/paste artifact",),
    "Architecture review": ("the verdict",),
    "Classroom artifact": ("requested artifact, preview, or content specification",),
    "Scheduled monitoring": ("resolved target", "actual scheduled behavior"),
    "Read-only handoff": ("verified finding", "recipient and next action"),
}

MATRIX_CASES = (
    "Case 1 - Simple Factual Status",
    "Case 2 - GitHub Read-Only Investigation",
    "Case 3 - Issue Implementation Report",
    "Case 4 - PR Review / Post-PR Handoff",
    "Case 5 - Blocked Source-Of-Truth Request",
    "Case 6 - Single Command Delivery",
    "Case 7 - Architecture Review",
    "Case 8 - Classroom Artifact Response",
    "Case 9 - Scheduled Monitoring Confirmation",
    "Case 10 - Read-Only Handoff",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalized(path: Path) -> str:
    return " ".join(read(path).split())


def section(path: Path, heading: str) -> str:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text, f"missing section '{heading}' in {path}"
    body = text.split(marker, 1)[1].split("\n## ", 1)[0]
    return " ".join(body.split())


def profile_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in section_lines(STANDARD, "Presentation Profiles"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) != 2 or columns[0] == "Profile":
            continue
        rows[columns[0]] = columns[1]
    return rows


def section_lines(path: Path, heading: str) -> list[str]:
    text = read(path)
    marker = f"## {heading}\n"
    assert marker in text, f"missing section '{heading}' in {path}"
    return text.split(marker, 1)[1].split("\n## ", 1)[0].splitlines()


def base_field_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in section_lines(STANDARD, "Base Report Contract"):
        if not line.startswith("|") or line.startswith("|---"):
            continue
        columns = [part.strip() for part in line.strip("|").split("|")]
        if len(columns) != 3 or columns[0] == "Field":
            continue
        rows[columns[0].strip("`")] = columns[2]
    return rows


def test_one_canonical_standard_owns_the_contract() -> None:
    text = section(STANDARD, "Authority And Precedence")
    assert "This standard owns the required field set" in text
    assert "presentation profiles" in text
    assert "visible ordering" in text
    for pointer in (
        "AGENTS.md",
        "02_Agent_Overlays/_common-overlay-rules.md",
        "final-report-standard.md",
        "07_Agent_Tests/agent-output-schema.md",
    ):
        assert pointer in text
    assert "compatibility pointers" in text


def test_every_base_field_has_exactly_one_value_owner() -> None:
    rows = base_field_rows()
    assert tuple(rows) == BASE_FIELDS
    for field, owner in rows.items():
        assert owner, f"{field} has no declared value owner"


def test_precedence_defers_value_ownership_to_canonical_contracts() -> None:
    text = section(STANDARD, "Authority And Precedence")
    for contract in (
        "IssueOperationalState",
        "AgentOperatingModeDecision",
        "executor route",
        "post-PR state audit",
        "validation",
        "sprint-reporting-schema.md",
        "Scheduler",
    ):
        assert contract in text
    assert "Governance stop conditions and write authorization control first" in text


def test_conditional_groups_are_not_forced_on_every_profile() -> None:
    text = section(STANDARD, "Conditional Field Groups")
    for field in ROUTING_FIELDS:
        assert f"`{field}`" in text
    for field in GITHUB_FIELDS:
        assert field in text
    assert "only when routing is material" in text
    assert "only when repository implementation or review" in text
    assert "No profile is required to display every field." in text


def test_ten_presentation_profiles_have_required_ordering() -> None:
    rows = profile_rows()
    assert set(rows) == set(PROFILE_ORDERING)
    for profile, phrases in PROFILE_ORDERING.items():
        for phrase in phrases:
            assert phrase in rows[profile], f"{profile}: missing '{phrase}'"


def test_governance_never_displaces_the_requested_output() -> None:
    text = section(STANDARD, "Presentation Profiles")
    assert "never displace" in text
    assert "unless a stop condition applies" in text
    assert "governance and report fields follow it" in text


def test_classroom_receipt_order_reuses_artifact_first_by_reference() -> None:
    text = section(STANDARD, "Presentation Profiles")
    for surface in (
        "live artifact link",
        "current preview or export",
        "genuine before/after evidence",
        "change and QA summary",
        "evidence limitations",
        "governance fields",
    ):
        assert surface in text
    assert "Never fabricate" in text

    precedence = section(STANDARD, "Authority And Precedence")
    assert "artifact-first-response-standard.md" in precedence
    assert "teacher-decision-studio-standard.md" in precedence
    assert "refine one profile without changing field ownership" in precedence

    # Domain policy stays where it lives; the standard must not copy it.
    standard_text = normalized(STANDARD)
    assert "Other / Build My Own" not in standard_text
    assert "Blocked-Production Behavior" not in standard_text


def test_progress_rules_require_canonical_evidence_and_reject_percentages() -> None:
    text = section(STANDARD, "Progress And Evidence Rules")
    assert "Render progress from named canonical states and evidence" in text
    assert "Never persist a parallel progress record" in text
    assert "workflow-state engine, or conversation-state service" in text
    for label in ("`verified`", "`inferred`", "`proposed`", "`blocked`", "`completed`"):
        assert label in text
    assert "Reject percentages unless a canonical contract supplies the completion signal" in text
    assert "never overrides live canonical evidence" in text


def test_presentation_grants_no_execution_authority() -> None:
    purpose = section(STANDARD, "Purpose")
    assert "creates no operational state, readiness, approval, execution, or write authority" in purpose
    progress = section(STANDARD, "Progress And Evidence Rules")
    assert "Presentation never implies execution authority" in progress
    assert "never reported as executed" in progress


def test_status_enum_stays_compatible_with_the_serialization_reference() -> None:
    rows = base_field_rows()
    assert rows["status"] == "this standard"
    standard_text = normalized(STANDARD)
    assert "`pass`, `fail`, `blocked`, or `deferred`" in standard_text
    assert "`status` is `blocked` only with a non-empty `blockers`" in standard_text

    schema = normalized(OUTPUT_SCHEMA)
    assert '"status": "pass|fail|blocked|deferred"' in schema
    for field in BASE_FIELDS:
        assert f'"{field}"' in schema


def test_test_directory_documents_are_not_independent_policy_sources() -> None:
    schema = normalized(OUTPUT_SCHEMA)
    assert "Test-facing compatibility reference only" in schema
    assert CANONICAL_PATH in schema
    assert "not an independent policy source" in schema
    assert "the canonical standard wins" in schema

    checklist = normalized(TEST_CHECKLIST)
    assert "This folder verifies behavior and never defines it" in checklist
    assert CANONICAL_PATH in checklist

    matrix = normalized(PROFILE_MATRIX)
    assert "Verification-only fixtures" in matrix
    assert "scores behavior and defines none of it" in matrix


def test_profile_matrix_covers_every_required_fixture_on_both_axes() -> None:
    text = read(PROFILE_MATRIX)
    for case in MATRIX_CASES:
        assert f"## {case}\n" in text, case
        body = section(PROFILE_MATRIX, case)
        assert "Ordering:" in body, case
        assert "Summary:" in body, case
    assert text.count("\nOrdering:") == len(MATRIX_CASES)
    assert text.count("\nSummary:") == len(MATRIX_CASES)


def test_classroom_receipt_regressions_cover_all_seven_scenarios() -> None:
    classroom = section(PROFILE_MATRIX, "Case 8 - Classroom Artifact Response")
    assert "Classroom Receipt Regression Fixtures (#1061)" in classroom
    for fixture in (
        "Slides + PDF + genuine before/after",
        "Slides + PDF + historical visual unavailable",
        "Docs + appropriate export",
        "Unsupported export",
        "No-op/read-only",
        "Failed write",
        "Multiple edited artifacts",
    ):
        assert fixture in classroom
    for behavior in (
        "genuine prior/current renders",
        "historical visual rendering is unavailable",
        "never fabricates a screenshot, thumbnail, PDF, or visual diff",
        "current export when supported and materially useful",
        "without treating the omission as failure",
        "does not claim an artifact-complete delivery receipt",
        "blocker-first under the Blocked work profile",
        "each verified artifact receives its own direct link",
        "no primary artifact is invented",
    ):
        assert behavior in classroom


def test_blocked_and_command_fixtures_lead_with_the_required_output() -> None:
    blocked = section(PROFILE_MATRIX, "Case 5 - Blocked Source-Of-Truth Request")
    assert "controlling blocker and its exact unblock condition first" in blocked
    assert "`status: blocked` with non-empty `blockers`" in blocked

    command = section(PROFILE_MATRIX, "Case 6 - Single Command Delivery")
    assert "one reusable copy/paste artifact first" in command
    assert "no implied execution" in command

    monitoring = section(PROFILE_MATRIX, "Case 9 - Scheduled Monitoring Confirmation")
    assert "resolved target and the actual scheduled behavior first" in monitoring
    assert "no persisted progress record, no percentage" in monitoring


def test_classroom_fixture_preserves_artifact_first_and_decision_studio() -> None:
    classroom = section(PROFILE_MATRIX, "Case 8 - Classroom Artifact Response")
    assert "requested artifact, preview, or content specification first" in classroom
    assert "artifact-first-response-standard.md" in classroom
    assert "Teacher Decision Studio standards" in classroom
    assert "destinations are unchanged" in classroom
    assert "never fabricated" in classroom

    # The consumed standards themselves stay unchanged in substance.
    assert "0.1.0" in section(ARTIFACT_FIRST, "Version")
    assert "0.1.0" in section(TEACHER_STUDIO, "Version")
    assert "Required Order" in read(ARTIFACT_FIRST)
    assert "Locked Interaction Model" in read(TEACHER_STUDIO)


def test_pointer_surfaces_reference_the_canonical_standard() -> None:
    final_report = normalized(FINAL_REPORT)
    assert "canonical in `agent-interaction-output-standard.md`" in final_report
    assert "compatibility pointer" in final_report
    assert "must not define a competing output schema" in final_report
    assert "0.3.0" in section(FINAL_REPORT, "Version")

    overlay = normalized(COMMON_OVERLAY)
    assert "- Agent Interaction Output Standard 0.1.0" in read(COMMON_OVERLAY)
    assert CANONICAL_PATH in overlay
    assert "they do not restate its fields, profiles, or ordering" in overlay

    agents = section(AGENTS, "Required Final Report")
    assert CANONICAL_PATH in agents
    assert "canonical owner of report field ownership" in agents

    assert "agent-interaction-output-standard.md" in normalized(GLOBAL_README)


def test_orchestrator_inherits_the_standard_without_a_competing_schema() -> None:
    text = read(ORCHESTRATOR)
    assert f"- `{CANONICAL_PATH}`" in text
    ordering = section(ORCHESTRATOR, "Response Ordering Rule")
    assert CANONICAL_PATH in ordering
    assert "never displace the requested answer or artifact" in ordering
    assert "do not create a competing output schema" in ordering
    assert "0.2.0" in section(ORCHESTRATOR, "Version")

    fixtures = read(ORCHESTRATOR_TESTS)
    assert "interaction-output-profile-matrix.md" in fixtures
    assert "## Test 27 - Profile Ordering Is Predictable\n" in fixtures
    assert "## Test 28 - Presentation Grants No Authority\n" in fixtures


def test_standard_is_registered_and_navigable() -> None:
    assert "| Agent Interaction Output Standard | 0.2.0 |" in read(VERSION_MAP)
    navigation = read(NAVIGATION)
    assert "@interaction-output" in navigation
    assert CANONICAL_PATH in navigation
