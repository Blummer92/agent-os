"""AOS-AUTO1H end-to-end: real live-input adapters feed the unchanged #1105
``prepare_candidate_packet`` entrypoint.

Uses the real ``LiveIssueReader``, ``LiveRepositoryEvidenceReader``, and
``build_repository_observation_from_verifier_stdout`` objects, but every
input is an injected fake/offline double (a fake ``SingleIssueTransport`` and
a literal ``verify-repo-state.sh`` stdout capture) so this test stays
offline and deterministic -- it never depends on live GitHub or a real
subprocess.

Because ``LiveRepositoryEvidenceReader`` is truthfully ``UNAVAILABLE`` for
both dependency and validation evidence (there is no structured live source
for either), the readiness stage's own existing logic
(``readiness_stage.py``'s ``UNAVAILABLE`` -> ``Status.FAIL`` mapping) is
expected to stop the pipeline at readiness with a ``blocked`` disposition --
exactly the same canonical logic the fixture-backed
``RESOLVED_CLEAR`` tests in ``tests/agent_os_candidate_packet`` exercise for
the opposite input. Nothing here is patched to force a ``GO``/``ready``
result.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for _path in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from scripts.agent_os_candidate_packet.cli import (  # noqa: E402
    PreparedCandidatePacket,
    prepare_candidate_packet,
)
from scripts.agent_os_candidate_packet.stage_models import (  # noqa: E402
    IssueReadinessStageStatus,
)
from scripts.agent_os_candidate_packet_live_input.issue_reader import (  # noqa: E402
    LiveIssueReader,
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
)
from scripts.agent_os_candidate_packet_live_input.repository_observation import (  # noqa: E402
    build_repository_observation_from_verifier_stdout,
)
from scripts.agent_os_candidate_packet_live_input.repository_reader import (  # noqa: E402
    LiveRepositoryEvidenceReader,
)
from scripts.agent_os_execution_capabilities import (  # noqa: E402
    RepositoryEvidenceType,
    RepositoryIdentity,
)

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 91155
_HEAD_SHA = "b89de18da472a3cd79877c4f7ee13b49bd7014eb"
_BASE_SHA = "c" * 40
_BRANCH = "agent/1155-e2e-live-input"

_BODY = """Tier: 0

## Objective
Prove #1155's live-input adapters feed #1105 unchanged.

## Owner
integration-manager

## Allowed Files
- scripts/agent_os_candidate_packet_live_input/README.md

## Validation
python3 -m compileall -q scripts/agent_os_candidate_packet_live_input

## Completion
Tests pass.

## Prior scope, duplicate, and supersession review
No duplicate work found; this is a live-input-adapter end-to-end fixture.

```yaml
agent_os_issue_acceptance:
  profile_version: issueplan-core/v1
  entity_id: issue-1155-e2e
  owner_agent: integration-manager
  source_of_truth: GitHub
  external_writes: none
  required_files:
    - scripts/agent_os_candidate_packet_live_input/README.md
  forbidden_paths:
    - .github/workflows
  required_tests:
    - python3 -m compileall -q scripts/agent_os_candidate_packet_live_input
  required_docs: []
  manual_review: []
  documentation_impact: docs-not-required
  documentation_expected_change: null
  documentation_exemption_reason: no docs needed
```
"""

_ISSUE_ITEM = {
    "number": _ISSUE_NUMBER,
    "title": "AOS-AUTO1H live-input end-to-end fixture",
    "state": "open",
    "html_url": f"https://github.com/{_REPOSITORY}/issues/{_ISSUE_NUMBER}",
    "created_at": "2026-08-15T00:00:00Z",
    "updated_at": "2026-08-15T00:00:00Z",
    "body": _BODY,
    "labels": ["agent-os"],
}


class _FakeSingleIssueTransport:
    """Offline double for the injected live-GitHub single-issue transport."""

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        return SingleIssueTransportResult(
            outcome=SingleIssueTransportOutcome.OK, item=dict(_ISSUE_ITEM)
        )


def _verifier_stdout() -> str:
    return "\n".join(
        [
            f"HEAD_REF={_BRANCH}",
            f"HEAD_SHA={_HEAD_SHA}",
            "BASE_REF=origin/main",
            f"BASE_SHA={_BASE_SHA}",
            "CHANGED_FILES_BEGIN",
            "scripts/agent_os_candidate_packet_live_input/README.md",
            "CHANGED_FILES_END",
        ]
    )


def test_live_adapters_feed_unchanged_prepare_candidate_packet_entrypoint() -> None:
    issue_reader = LiveIssueReader(transport=_FakeSingleIssueTransport())
    repository_reader = LiveRepositoryEvidenceReader()

    result = prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=issue_reader,
        repository_reader=repository_reader,
        observed_at="2026-08-15T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_HEAD_SHA,
        invocation_id="candidate-packet-live-input-e2e-1155",
        evaluator_sha="a" * 40,
    )

    assert isinstance(result, PreparedCandidatePacket)
    assert result.source_revision is not None


def test_truthfully_unavailable_evidence_stops_at_readiness_blocked() -> None:
    """Truthful UNAVAILABLE evidence must not be patched into a fabricated GO."""
    issue_reader = LiveIssueReader(transport=_FakeSingleIssueTransport())
    repository_reader = LiveRepositoryEvidenceReader()

    result = prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=issue_reader,
        repository_reader=repository_reader,
        observed_at="2026-08-15T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_HEAD_SHA,
        invocation_id="candidate-packet-live-input-e2e-1155",
        evaluator_sha="a" * 40,
    )

    assert result.readiness_stage_result.status is IssueReadinessStageStatus.BLOCKED
    assert "dependency.no-structured-source-configured" in result.readiness_stage_result.reason_codes
    assert "validation.no-structured-source-configured" in result.readiness_stage_result.reason_codes
    assert result.disposition == "blocked"
    assert result.packet is None
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_repository_observation_from_verifier_stdout_matches_evaluated_sha() -> None:
    """Proves the assembler output is a valid input to the same entrypoint parameter."""
    identity = RepositoryIdentity(host="github.com", owner="Blummer92", repository="agent-os")

    observation = build_repository_observation_from_verifier_stdout(
        _verifier_stdout(),
        producer_adapter="live-input-adapter",
        producer_adapter_version="0.1.0",
        correlation_id=f"issue-{_ISSUE_NUMBER}",
        repository_identity=identity,
        contract_fingerprint="3" * 64,
        observed_at="2026-08-15T00:05:00Z",
        freshness_boundary="main@1155-e2e",
        evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        requested_ref=_BRANCH,
        requested_sha=_HEAD_SHA,
        tested_sha=_HEAD_SHA,
        pushed_sha=None,
        proposed_pr_sha=None,
        synthetic_merge_sha=None,
        external_build_sha=None,
    )

    assert observation.head_sha == _HEAD_SHA
    assert observation.repository_identity == identity


def test_issue_number_mismatch_from_the_live_transport_fails_closed_through_the_pipeline() -> None:
    """A transport answering the wrong issue must never reach the pipeline as OK."""

    class _WrongIssueTransport:
        def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
            wrong_item = dict(_ISSUE_ITEM, number=issue_number + 1)
            return SingleIssueTransportResult(
                outcome=SingleIssueTransportOutcome.OK, item=wrong_item
            )

    issue_reader = LiveIssueReader(transport=_WrongIssueTransport())
    repository_reader = LiveRepositoryEvidenceReader()

    result = prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=issue_reader,
        repository_reader=repository_reader,
        observed_at="2026-08-15T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_HEAD_SHA,
        invocation_id="candidate-packet-live-input-e2e-1155-mismatch",
        evaluator_sha="a" * 40,
    )

    assert result.stage_reached == "readiness"
    assert result.readiness_stage_result.status in (
        IssueReadinessStageStatus.SOURCE_FAILURE,
        IssueReadinessStageStatus.INCOMPLETE_EVIDENCE,
    )
    assert result.packet is None


# --- AOS-GCE2F (#1320) structured evidence reaches the unchanged entrypoint ----


def _structured_repository_reader(
    *,
    preparation_status=None,
    advisory_status: str = "passed",
):
    from scripts.agent_os_execution_capabilities.dependencies import (
        DependencyArtifactIdentity,
        DependencyCacheState,
        DependencyEcosystem,
        DependencyInstallMode,
        DependencyPreparationStatus,
        DependencyReadinessEvidence,
        ReproducibilityLevel,
        RequiredEnvironmentSpec,
    )
    from scripts.agent_os_execution_capabilities.models import RepositoryIdentity as _Identity
    from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult

    spec = RequiredEnvironmentSpec(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256="a" * 64
        ),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    status = preparation_status or DependencyPreparationStatus.READY
    readiness = DependencyReadinessEvidence(
        execution_surface_id="execution-surface:governed-runner",
        workspace_identity="workspace:1320",
        source_sha=_HEAD_SHA,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version="3.11.15",
        package_manager_version="25.2",
        declared_dependency_identity="declared:" + "c" * 64,
        lock_or_constraints_identity=None,
        install_mode=spec.install_mode,
        source_or_registry_identity="pypi.org/simple",
        cache_state=DependencyCacheState.CURRENT_COMPLETE,
        preparation_status=status,
        resolved_dependency_identity=(
            "resolved:" + "d" * 64
            if status is DependencyPreparationStatus.READY
            else None
        ),
        environment_health_evidence_id="environment-health:" + "f" * 64,
        observed_at="2026-08-15T00:00:00Z",
        expires_at="2026-08-15T02:00:00Z",
        reproducibility_level=ReproducibilityLevel.LOCKED,
    )
    advisory = AdvisoryEvidenceResult(
        schema_name="agent-os.advisory-evidence",
        schema_version="1.0",
        status=advisory_status,
        result_id="advisory-evidence:" + "1" * 64,
        repository_identity=_Identity(
            host="github.com", owner="Blummer92", repository="agent-os"
        ),
        pull_request=1321,
        base_branch="main",
        base_sha=_HEAD_SHA,
        source_head_sha=_HEAD_SHA,
        tested_sha=_HEAD_SHA,
        repository_evidence_type=None,
        projection_id="projection:" + "4" * 64,
        proposal_id="proposal:" + "5" * 64,
        approval_id="approval:" + "6" * 64,
        repository_state_evidence_id="repository-state:" + "7" * 64,
        implementation_contract_fingerprint="contract:" + "8" * 64,
        selector_version="v1",
        profile="python",
        command_set_digest="9" * 64,
        plan_id="validation-plan:" + "e" * 64,
        bundle_id="validation-evidence-bundle:" + "a" * 64,
        runner_id="runner:governed",
        invocation_id="invocation:" + "b" * 64,
        command_result_ids=(),
        command_result_statuses=(),
        reason_codes=(),
        details=(),
    )
    return LiveRepositoryEvidenceReader(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        required_environment_spec=spec,
        dependency_readiness=readiness,
        validation_result=advisory,
        evaluated_at="2026-08-15T00:05:00Z",
    )


def _prepare(repository_reader) -> PreparedCandidatePacket:
    return prepare_candidate_packet(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue_reader=LiveIssueReader(transport=_FakeSingleIssueTransport()),
        repository_reader=repository_reader,
        observed_at="2026-08-15T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_HEAD_SHA,
        invocation_id="candidate-packet-live-input-e2e-1320",
        evaluator_sha="a" * 40,
    )


def test_structured_evidence_no_longer_blocks_on_no_structured_source() -> None:
    """The production reader stops being unconditionally UNAVAILABLE (#1320)."""
    result = _prepare(_structured_repository_reader())

    reasons = result.readiness_stage_result.reason_codes
    assert "dependency.no-structured-source-configured" not in reasons
    assert "validation.no-structured-source-configured" not in reasons
    assert result.readiness_stage_result.status is IssueReadinessStageStatus.READY
    # Readiness is not authorization: the pipeline still stops on its own gate.
    assert "authorization.not-granted" in reasons
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False


def test_blocked_dependency_preparation_still_blocks_the_pipeline() -> None:
    from scripts.agent_os_execution_capabilities.dependencies import (
        DependencyPreparationStatus,
    )

    result = _prepare(
        _structured_repository_reader(
            preparation_status=DependencyPreparationStatus.BLOCKED
        )
    )

    assert "dependency.preparation-blocked" in result.readiness_stage_result.reason_codes
    assert result.disposition == "blocked"
    assert result.packet is None


def test_stale_validation_evidence_still_fails_closed_end_to_end() -> None:
    result = _prepare(_structured_repository_reader(advisory_status="stale"))

    assert "validation.advisory-stale" in result.readiness_stage_result.reason_codes
    assert result.disposition == "blocked"
    assert result.packet is None
