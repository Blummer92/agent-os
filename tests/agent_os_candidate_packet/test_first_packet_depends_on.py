"""Focused #3354 tests: structured IssuePlan ``depends_on`` + phase-aware readiness.

Covers the canonical ``owner/repository#NNNN`` dependency-identity field
(issueplan-core/v1), its scanner/current-state/fingerprint propagation, the
bounded pre-approval dependency evidence producer, and first-packet readiness
keyed on the absence of any ApprovalRecord -- never on phase alone.
"""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_candidate_packet.cli import _prepare_from_fixture, main
from scripts.agent_os_candidate_packet.preapproval_dependency_evidence import (
    build_preapproval_dependency_evidence,
    parse_depends_on_identity,
)
from scripts.agent_os_candidate_packet.readiness_stage import prepare_issue_readiness
from scripts.agent_os_candidate_packet.stage_models import (
    DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON,
    DependencyEvidence,
    DependencyIdentityEvidence,
    DependencyIdentityStatus,
    EvidenceStatus,
    IssueReadinessStageRequest,
    IssueReadinessStageStatus,
    IssueReadResult,
    IssueReadStatus,
)
from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    build_issueplan_current_state_evidence,
    compute_issueplan_current_state_fingerprint,
)
from scripts.agent_os_issue_acceptance.issueplan_scanner import (
    AdoptionClass,
    ScanFinding,
    SourceEnvelope,
    normalize_depends_on,
    scan_issueplan_source,
)

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 33540
_OBSERVED_AT = "2026-10-07T00:00:00Z"

_STRICT_FIELDS = """  profile_version: issueplan-core/v1
  entity_id: aos-fp1-3354
  owner_agent: candidate-packet-agent
  source_of_truth: scripts/agent_os_candidate_packet/
  external_writes: none
  required_files: []
  forbidden_paths: []
  required_tests: []
  required_docs: []
  banned_patterns: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: no doc changes needed"""


def _body(depends_on_block: str = "") -> str:
    return f"""Tier: 0

## Objective
First-packet fixture.

## Owner
candidate-packet-agent

## Allowed Files
- scripts/agent_os_candidate_packet/

## Validation
python -m pytest tests/agent_os_candidate_packet/test_first_packet_depends_on.py

## Completion
Tests pass.

## Prior scope, duplicate, and supersession review
No duplicate work found; this is a new bounded stage.

```yaml
agent_os_issue_acceptance:
{_STRICT_FIELDS}
{depends_on_block}
```
"""


def _item(body: str, number: int = _ISSUE_NUMBER, state: str = "open") -> dict:
    return {
        "number": number,
        "title": f"fixture-{number}",
        "state": state,
        "body": body,
        "html_url": f"https://github.com/{_REPOSITORY}/issues/{number}",
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-02T00:00:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [],
    }


class _MapIssueReader:
    """Serves canned issues by (repository, number); unknown -> NOT_FOUND."""

    def __init__(self, items: dict[tuple[str, int], dict]) -> None:
        self._items = items

    def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
        item = self._items.get((repository, issue_number))
        if item is None:
            return IssueReadResult(status=IssueReadStatus.NOT_FOUND, item=None)
        return IssueReadResult(status=IssueReadStatus.OK, item=dict(item))


class _ExplodingRepositoryReader:
    """Proves first-packet mode never consults the post-approval reader."""

    def read_dependency_evidence(self, repository: str, issue_number: int):
        raise AssertionError("repository_reader consulted in first-packet mode")

    def read_validation_evidence(self, repository: str, issue_number: int):
        raise AssertionError("repository_reader consulted in first-packet mode")


class _LegacyRepositoryReader:
    def __init__(self, dependency=None, validation=None) -> None:
        from scripts.agent_os_candidate_packet.stage_models import ValidationEvidence

        self._dependency = dependency or DependencyEvidence(EvidenceStatus.RESOLVED_CLEAR)
        self._validation = validation or ValidationEvidence(EvidenceStatus.RESOLVED_CLEAR)

    def read_dependency_evidence(self, repository: str, issue_number: int):
        return self._dependency

    def read_validation_evidence(self, repository: str, issue_number: int):
        return self._validation


def _request(**overrides) -> IssueReadinessStageRequest:
    values = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        observed_at=_OBSERVED_AT,
        approval_record_exists=False,
    )
    values.update(overrides)
    return IssueReadinessStageRequest(**values)


def _depends_on_items(*numbers: int, states: dict[int, str] | None = None) -> dict:
    states = states or {}
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body(_depends_on_block(numbers)))}
    for number in numbers:
        items[(_REPOSITORY, number)] = _item(
            _body(), number=number, state=states.get(number, "closed")
        )
    return items


def _depends_on_block(numbers: tuple[int, ...]) -> str:
    lines = "".join(f"\n    - {_REPOSITORY}#{number}" for number in numbers)
    return f"  depends_on:{lines}" if numbers else "  depends_on: []"


# --------------------------------------------------------------------------
# Scanner: depends_on is a governed structured field.
# --------------------------------------------------------------------------


def _scan(body: str):
    envelope = SourceEnvelope(
        source_locator=f"github:{_REPOSITORY}#{_ISSUE_NUMBER}",
        source_revision="rev-1",
        content=body,
    )
    return scan_issueplan_source(envelope)


def test_depends_on_is_governed_not_unknown() -> None:
    result = _scan(_body(_depends_on_block((101, 102))))
    assert ScanFinding.UNKNOWN_GOVERNED_FIELD not in result.findings
    assert result.strict_valid is True
    assert result.adoption_class == AdoptionClass.STRICT_NATIVE


def test_depends_on_absent_keeps_strict_valid() -> None:
    result = _scan(_body())
    assert result.strict_valid is True
    assert ScanFinding.UNKNOWN_GOVERNED_FIELD not in result.findings


def test_depends_on_empty_list_is_a_positive_none_declaration() -> None:
    result = _scan(_body("  depends_on: []"))
    assert result.strict_valid is True
    candidate = result.candidates[0]
    assert candidate.parsed is not None
    assert candidate.parsed["depends_on"] == []


def test_depends_on_normalized_sorted_and_deduplicated() -> None:
    body = _body(
        "  depends_on:\n"
        f"    - {_REPOSITORY}#102\n"
        f"    - {_REPOSITORY}#101\n"
        f"    - {_REPOSITORY}#101\n"
    )
    result = _scan(body)
    assert result.strict_valid is True
    candidate = result.candidates[0]
    assert candidate.parsed is not None
    assert candidate.parsed["depends_on"] == [
        f"{_REPOSITORY}#101",
        f"{_REPOSITORY}#102",
    ]


@pytest.mark.parametrize(
    "field",
    (
        "  depends_on: not-a-list",
        "  depends_on: 101",
        "  depends_on:\n    - '#101'",
        "  depends_on:\n    - 'owner/repo#abc'",
        "  depends_on:\n    - 'owner/repo#0'",
        "  depends_on:\n    - 'owner/repo#01'",
        "  depends_on:\n    - 'https://github.com/owner/repo/issues/101'",
        "  depends_on:\n    - 101",
        "  depends_on:\n    - ''",
        "  depends_on:\n    - 'owner//repo#101'",
    ),
)
def test_depends_on_malformed_fails_closed(field: str) -> None:
    result = _scan(_body(field))
    assert ScanFinding.METADATA_MALFORMED in result.findings
    assert result.adoption_class == AdoptionClass.ADOPTION_BLOCKED
    assert result.strict_valid is False


@pytest.mark.parametrize(
    "value, expected",
    (
        (None, ()),
        ([], ()),
        (["Blummer92/agent-os#2", "Blummer92/agent-os#1"], ("Blummer92/agent-os#1", "Blummer92/agent-os#2")),
        ("nope", None),
        (["#1"], None),
        ([101], None),
        ({"a": 1}, None),
    ),
)
def test_normalize_depends_on_unit(value, expected) -> None:
    assert normalize_depends_on(value) == expected


# --------------------------------------------------------------------------
# Current state: the fingerprint covers depends_on.
# --------------------------------------------------------------------------


def _evidence(body: str):
    envelope = SourceEnvelope(
        source_locator=f"github:{_REPOSITORY}#{_ISSUE_NUMBER}",
        source_revision="rev-1",
        content=body,
    )
    scan_result = scan_issueplan_source(envelope)
    return build_issueplan_current_state_evidence(
        envelope,
        scan_result,
        observed_at=_OBSERVED_AT,
        freshness_boundary="test",
    )


def test_fingerprint_covers_depends_on() -> None:
    base = _evidence(_body())
    with_deps = _evidence(_body(_depends_on_block((101,))))
    assert (
        compute_issueplan_current_state_fingerprint(base)
        != compute_issueplan_current_state_fingerprint(with_deps)
    )


def test_fingerprint_stable_for_identical_depends_on() -> None:
    first = _evidence(_body(_depends_on_block((102, 101))))
    second = _evidence(_body("  depends_on:\n    - Blummer92/agent-os#101\n    - Blummer92/agent-os#102"))
    assert (
        compute_issueplan_current_state_fingerprint(first)
        == compute_issueplan_current_state_fingerprint(second)
    )


def test_fingerprint_stable_without_depends_on() -> None:
    # Plans that predate the field keep byte-identical fingerprints: the
    # evidence schema version is unchanged and projection is additive.
    first = _evidence(_body())
    second = _evidence(_body())
    assert (
        compute_issueplan_current_state_fingerprint(first)
        == compute_issueplan_current_state_fingerprint(second)
    )


# --------------------------------------------------------------------------
# Producer: pre-approval issue-dependency evidence.
# --------------------------------------------------------------------------


def _producer(identities, items, provenance="issueplan:depends_on@test"):
    return build_preapproval_dependency_evidence(
        repository=_REPOSITORY,
        dependency_identities=tuple(identities),
        issue_reader=_MapIssueReader(items),
        provenance=provenance,
    )


def test_producer_no_dependencies_is_clear() -> None:
    evidence = _producer([], {})
    assert evidence.status == EvidenceStatus.RESOLVED_CLEAR
    assert evidence.reason_codes == ("dependency-graph.no-dependencies-declared",)


def test_producer_all_closed_is_clear() -> None:
    items = _depends_on_items(101, 102)
    evidence = _producer((f"{_REPOSITORY}#101", f"{_REPOSITORY}#102"), items)
    assert evidence.status == EvidenceStatus.RESOLVED_CLEAR
    assert evidence.reason_codes == ("dependency-graph.all-dependencies-closed",)


def test_producer_open_dependency_blocks() -> None:
    items = _depends_on_items(101, 102, states={102: "open"})
    evidence = _producer((f"{_REPOSITORY}#101", f"{_REPOSITORY}#102"), items)
    assert evidence.status == EvidenceStatus.RESOLVED_BLOCKED
    assert evidence.reason_codes == ("dependency-graph.open-dependencies",)
    assert any("open=Blummer92/agent-os#102" in detail for detail in evidence.details)


def test_producer_missing_dependency_is_unavailable() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body())}
    evidence = _producer((f"{_REPOSITORY}#101",), items)
    assert evidence.status == EvidenceStatus.UNAVAILABLE
    assert evidence.reason_codes == ("dependency-graph.state-unavailable",)


def test_producer_malformed_state_is_unavailable() -> None:
    items = _depends_on_items(101)
    items[(_REPOSITORY, 101)] = _item(_body(), number=101, state="weird")
    evidence = _producer((f"{_REPOSITORY}#101",), items)
    assert evidence.status == EvidenceStatus.UNAVAILABLE


def test_producer_reader_error_is_unavailable() -> None:
    class _RaisingReader:
        def read_issue(self, repository: str, issue_number: int) -> IssueReadResult:
            raise RuntimeError("transport exploded")

    evidence = build_preapproval_dependency_evidence(
        repository=_REPOSITORY,
        dependency_identities=(f"{_REPOSITORY}#101",),
        issue_reader=_RaisingReader(),
        provenance="issueplan:depends_on@test",
    )
    assert evidence.status == EvidenceStatus.UNAVAILABLE


def test_producer_rejects_non_canonical_identity() -> None:
    evidence = _producer(("#101",), {})
    assert evidence.status == EvidenceStatus.UNAVAILABLE
    assert evidence.reason_codes == ("dependency-graph.identity-malformed",)


def test_producer_requires_provenance() -> None:
    with pytest.raises(ValueError):
        build_preapproval_dependency_evidence(
            repository=_REPOSITORY,
            dependency_identities=(),
            issue_reader=_MapIssueReader({}),
            provenance="",
        )


@pytest.mark.parametrize(
    "identity, expected",
    (
        ("Blummer92/agent-os#101", ("Blummer92/agent-os", 101)),
        ("o/r#1", ("o/r", 1)),
        ("#101", None),
        ("Blummer92/agent-os#0", None),
        ("nota ref", None),
        (101, None),
    ),
)
def test_parse_depends_on_identity(identity, expected) -> None:
    assert parse_depends_on_identity(identity) == expected


# --------------------------------------------------------------------------
# Architecture boundary: the producer reaches no I/O surface.
# --------------------------------------------------------------------------


def test_producer_module_has_no_io_shaped_imports() -> None:
    import ast
    import inspect
    from pathlib import Path

    import scripts.agent_os_candidate_packet.preapproval_dependency_evidence as module

    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    allowed = {
        "__future__",
        "collections.abc",
        "scripts.agent_os_issue_acceptance.issueplan_scanner",
        ".stage_models",
    }
    assert not names - allowed, f"producer gained imports: {sorted(names - allowed)}"


# --------------------------------------------------------------------------
# Readiness: first-packet mode.
# --------------------------------------------------------------------------


def test_first_packet_ready_with_closed_dependencies() -> None:
    items = _depends_on_items(101, 102)
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.READY
    identity = result.dependency_identity_evidence
    assert identity is not None
    assert identity.status == DependencyIdentityStatus.RESOLVED
    assert identity.dependency_ids == (
        "Blummer92/agent-os#101",
        "Blummer92/agent-os#102",
    )
    assert "dependency-graph.all-dependencies-closed" in result.reason_codes
    assert "validation.first-packet-not-required" in result.reason_codes
    assert "authorization.not-granted" in result.reason_codes


def test_first_packet_open_dependency_blocks() -> None:
    items = _depends_on_items(101, 102, states={102: "open"})
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert "dependency-graph.open-dependencies" in result.reason_codes


def test_first_packet_missing_dependency_fails_closed() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body(_depends_on_block((101,))))}
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert "dependency-graph.state-unavailable" in result.reason_codes


def test_first_packet_malformed_depends_on_blocks() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body("  depends_on: nope"))}
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert result.readiness_result is not None
    assert any(
        "reason_code=first-packet.issueplan-not-strict" in check.evidence
        for check in result.readiness_result.report.checks
    )


def test_first_packet_without_depends_on_field_is_ready_and_absent() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body())}
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.READY
    identity = result.dependency_identity_evidence
    assert identity is not None
    assert identity.status == DependencyIdentityStatus.ABSENT
    assert identity.dependency_ids == ()


def test_first_packet_requires_strict_issueplan() -> None:
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item("no metadata here")}
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert result.readiness_result is not None
    assert any(
        "reason_code=first-packet.issueplan-not-strict" in check.evidence
        for check in result.readiness_result.report.checks
    )


def test_first_packet_prose_dependencies_never_become_identities() -> None:
    body = _body() + "\n## Dependencies\nDepends on: #101\nBlocked by Blummer92/agent-os#102.\n"
    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(body)}
    result = prepare_issue_readiness(
        _request(), _MapIssueReader(items), _ExplodingRepositoryReader()
    )
    assert result.status == IssueReadinessStageStatus.READY
    identity = result.dependency_identity_evidence
    assert identity is not None
    assert identity.status == DependencyIdentityStatus.ABSENT
    assert identity.dependency_ids == ()
    assert not any("101" in code for code in result.reason_codes)


def test_first_packet_conflicting_caller_identities_needs_decision() -> None:
    items = _depends_on_items(101)
    caller = DependencyIdentityEvidence(
        status=DependencyIdentityStatus.RESOLVED,
        dependency_ids=("Blummer92/agent-os#101",),
        provenance=("caller:fixture",),
    )
    result = prepare_issue_readiness(
        _request(),
        _MapIssueReader(items),
        _ExplodingRepositoryReader(),
        dependency_identity_evidence=caller,
    )
    assert result.status == IssueReadinessStageStatus.NEEDS_DECISION
    identity = result.dependency_identity_evidence
    assert identity is not None
    assert "dependency-identity.conflicting-sources" in identity.reason_codes


def test_legacy_path_unchanged_when_approval_record_exists() -> None:
    items = _depends_on_items(101)
    dependency = DependencyEvidence(
        EvidenceStatus.UNAVAILABLE, reason_codes=("dependency.reader-error",)
    )
    result = prepare_issue_readiness(
        _request(approval_record_exists=True),
        _MapIssueReader(items),
        _LegacyRepositoryReader(dependency=dependency),
    )
    # Legacy contract preserved: the repository reader is consulted and its
    # UNAVAILABLE evidence fails closed exactly as before.
    assert result.status == IssueReadinessStageStatus.BLOCKED
    assert result.dependency_identity_evidence is not None
    assert (
        DEPENDENCY_IDENTITY_NOT_SUPPLIED_REASON
        in result.dependency_identity_evidence.reason_codes
    )


def test_mode_keyed_on_approval_record_not_phase() -> None:
    """The same fixture takes the legacy path with an approval record and the
    first-packet path without one: phase alone never selects the contract."""
    items = _depends_on_items(101)
    legacy = prepare_issue_readiness(
        _request(approval_record_exists=True),
        _MapIssueReader(items),
        _LegacyRepositoryReader(),
    )
    first_packet = prepare_issue_readiness(
        _request(approval_record_exists=False),
        _MapIssueReader(items),
        _ExplodingRepositoryReader(),
    )
    assert legacy.status == IssueReadinessStageStatus.READY
    assert "validation.first-packet-not-required" not in legacy.reason_codes
    assert first_packet.status == IssueReadinessStageStatus.READY
    assert "validation.first-packet-not-required" in first_packet.reason_codes


def test_request_rejects_non_bool_approval_record_exists() -> None:
    with pytest.raises(TypeError):
        _request(approval_record_exists="yes")


def test_prepare_candidate_packet_first_packet_reaches_planning_ready() -> None:
    from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet

    items = {(_REPOSITORY, _ISSUE_NUMBER): _item(_body("  depends_on: []"))}
    result = prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=_MapIssueReader(items),
        repository_reader=_ExplodingRepositoryReader(),
        observed_at=_OBSERVED_AT,
        base_branch="main",
        evaluated_repository_sha="a" * 40,
        invocation_id="fp-3354-test",
        evaluator_sha="b" * 40,
        approval_record_exists=False,
    )
    assert result.stage_reached == "planning"
    assert result.disposition == "ready"
    assert result.readiness_stage_result is not None
    assert result.readiness_stage_result.status == IssueReadinessStageStatus.READY
    assert result.planning_stage_result is not None
    assert result.planning_stage_result.status.value == "ready"


def test_first_packet_closed_dependencies_keep_batch_scheduling_boundary() -> None:
    """Pre-existing batch semantic, unchanged by #3354: dependencies that are
    not nodes of the supplied single-issue planning graph are
    ``unresolved-dependency`` for scheduling, even when the pre-approval
    evidence proved them closed. Readiness is READY; planning honestly
    reports needs-decision. Broadening this into dependency scheduling is
    explicitly out of scope."""
    from scripts.agent_os_candidate_packet.cli import prepare_candidate_packet

    items = _depends_on_items(101, 102)
    result = prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=_MapIssueReader(items),
        repository_reader=_ExplodingRepositoryReader(),
        observed_at=_OBSERVED_AT,
        base_branch="main",
        evaluated_repository_sha="a" * 40,
        invocation_id="fp-3354-test-deps",
        evaluator_sha="b" * 40,
        approval_record_exists=False,
    )
    assert result.readiness_stage_result is not None
    assert result.readiness_stage_result.status == IssueReadinessStageStatus.READY
    assert result.stage_reached == "planning"
    assert result.disposition == "needs-decision"
    assert result.planning_stage_result is not None
    planning_result = result.planning_stage_result.planning_result
    assert planning_result is not None
    assert any(
        "unresolved-dependency" in cohort.reason_codes
        for cohort in planning_result.cohorts
    )


def test_cli_fixture_first_packet_without_post_approval_evidence(tmp_path) -> None:
    """The operator fixture can express first-packet mode; the CLI never needs
    live GitHub access for it."""
    fixture = {
        "repository": _REPOSITORY,
        "issue_number": _ISSUE_NUMBER,
        "issue": _item(_body("  depends_on: []")),
        "observed_at": _OBSERVED_AT,
        "base_branch": "main",
        "evaluated_repository_sha": "a" * 40,
        "invocation_id": "fp-3354-cli",
        "evaluator_sha": "b" * 40,
        "approval_record_exists": False,
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    result = _prepare_from_fixture(json.loads(path.read_text(encoding="utf-8")))
    assert result.stage_reached == "planning"
    assert result.disposition == "ready"


def test_cli_fixture_legacy_default_still_requires_post_approval_evidence(
    tmp_path,
) -> None:
    fixture = {
        "repository": _REPOSITORY,
        "issue_number": _ISSUE_NUMBER,
        "issue": _item(_body("  depends_on: []")),
        "observed_at": _OBSERVED_AT,
        "base_branch": "main",
        "evaluated_repository_sha": "a" * 40,
        "invocation_id": "fp-3354-cli-legacy",
        "evaluator_sha": "b" * 40,
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    result = _prepare_from_fixture(json.loads(path.read_text(encoding="utf-8")))
    # No dependency/validation evidence supplied -> the legacy repository
    # reader reports UNAVAILABLE and readiness fails closed as before.
    assert result.disposition == "blocked"


def test_main_reports_first_packet_planning_outcome(tmp_path, capsys) -> None:
    fixture = {
        "repository": _REPOSITORY,
        "issue_number": _ISSUE_NUMBER,
        "issue": _item(_body("  depends_on: []")),
        "observed_at": _OBSERVED_AT,
        "base_branch": "main",
        "evaluated_repository_sha": "a" * 40,
        "invocation_id": "fp-3354-cli-main",
        "evaluator_sha": "b" * 40,
        "approval_record_exists": False,
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    exit_code = main(["--request", str(path), "--format", "json"])
    assert exit_code == 1  # no repository_observation -> stops at planning
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_reached"] == "planning"
    assert payload["disposition"] == "ready"
    assert payload["readiness_status"] == "ready"
