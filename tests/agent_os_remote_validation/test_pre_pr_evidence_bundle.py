from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_execution_capabilities.models import RepositoryEvidenceType
from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    PrePrValidationSubject,
    SuppliedCommandResult,
    compute_command_set_digest,
    pre_pr_validation_plan_id,
)
from scripts.agent_os_remote_validation.evidence_bundle import (
    reconstruct_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
    validation_evidence_bundle_id,
)
from scripts.agent_os_remote_validation.pre_pr_evidence_bundle import (
    build_pre_pr_validation_evidence_bundle,
    pre_pr_validation_evidence_bundle_id,
    reconstruct_pre_pr_validation_evidence_bundle,
    serialize_pre_pr_validation_evidence_bundle,
)
from tests.agent_os_remote_validation.test_evidence_bundle import (
    APPROVAL_ID,
    BASE_SHA,
    CONTRACT,
    EVIDENCE_ID,
    HEAD_SHA,
    PROPOSAL_ID,
    PROJECTION_ID,
    _identity,
    _projection,
)

COMMAND = "python -m pytest tests/agent_os_remote_validation"


def _plan() -> PrePrValidationPlan:
    subject = PrePrValidationSubject(
        repository="Blummer92/agent-os",
        issue_number=1985,
        invocation_id="pre-pr-1985",
        base_branch="main",
        base_sha=BASE_SHA,
        branch="agent/issue-1985-pre-validation-evidence-part2",
        expected_source_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        allowed_files=("tests/agent_os_remote_validation",),
        forbidden_paths=(".github/workflows",),
        required_command_identities=(COMMAND,),
        approval_id=APPROVAL_ID,
        approval_revision=1,
        projection_id=PROJECTION_ID,
        implementation_contract_fingerprint=CONTRACT,
        expected_changed_paths=("tests/agent_os_remote_validation",),
        candidate_bound=True,
    )
    return PrePrValidationPlan(
        selector_version="1.0.0",
        subject=subject,
        commands=(COMMAND,),
        command_set_digest=compute_command_set_digest("1.0.0", (COMMAND,)),
        reason_codes=("profile.focused-package",),
    )


def _result(plan: PrePrValidationPlan) -> SuppliedCommandResult:
    return SuppliedCommandResult(
        plan_id=pre_pr_validation_plan_id(plan),
        invocation_id=plan.subject.invocation_id,
        runner_id="dev-validation:remote-validation",
        command_ordinal=0,
        command=COMMAND,
        source_head_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
        status="passed",
        exit_code=0,
    )


def _bundle(plan: PrePrValidationPlan):
    return build_pre_pr_validation_evidence_bundle(
        _projection(),
        plan,
        (_result(plan),),
        expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID,
        expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
    )


def test_pr_less_bundle_carries_canonical_plan_without_dummy_pr() -> None:
    plan = _plan()
    bundle = _bundle(plan)

    assert bundle.status == "passed"
    assert bundle.pull_request is None
    assert bundle.validation_plan is plan
    assert bundle.plan_id == pre_pr_validation_plan_id(plan)
    assert bundle.execution_authorized is False
    payload = serialize_pre_pr_validation_evidence_bundle(bundle)
    assert payload["pull_request"] is None
    assert payload["validation_plan"]["subject"]["issue_number"] == 1985
    assert pre_pr_validation_evidence_bundle_id(bundle) == bundle.bundle_id


def test_pr_less_bundle_round_trips_without_positive_pr_assumption() -> None:
    plan = _plan()
    bundle = _bundle(plan)
    payload = serialize_pre_pr_validation_evidence_bundle(bundle)

    reconstructed = reconstruct_pre_pr_validation_evidence_bundle(payload)

    assert reconstructed.pull_request is None
    assert type(reconstructed.validation_plan) is PrePrValidationPlan
    assert reconstructed.validation_plan == plan
    assert pre_pr_validation_evidence_bundle_id(reconstructed) == bundle.bundle_id
    assert serialize_pre_pr_validation_evidence_bundle(reconstructed) == payload


def test_canonical_bundle_api_dispatches_pr_less_without_fabricating_pr() -> None:
    plan = _plan()
    bundle = _bundle(plan)

    payload = serialize_validation_evidence_bundle(bundle)
    reconstructed = reconstruct_validation_evidence_bundle(payload)

    assert payload["pull_request"] is None
    assert payload["validation_plan"]["subject"]["issue_number"] == 1985
    assert type(reconstructed.validation_plan) is PrePrValidationPlan
    assert reconstructed.validation_plan == plan
    assert reconstructed.pull_request is None
    assert validation_evidence_bundle_id(reconstructed) == bundle.bundle_id
    assert serialize_validation_evidence_bundle(reconstructed) == payload


def test_pr_less_bundle_rejects_fabricated_positive_pr() -> None:
    bundle = _bundle(_plan())
    with pytest.raises(ValueError, match="must not carry a pull request"):
        serialize_pre_pr_validation_evidence_bundle(replace(bundle, pull_request=1))


def test_pr_less_bundle_identity_changes_with_observed_result() -> None:
    plan = _plan()
    first = _bundle(plan)
    changed = SuppliedCommandResult(
        plan_id=pre_pr_validation_plan_id(plan),
        invocation_id=plan.subject.invocation_id,
        runner_id="dev-validation:remote-validation",
        command_ordinal=0,
        command=COMMAND,
        source_head_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
        status="passed",
        exit_code=0,
        diagnostic_summary="bounded observation",
    )
    second = build_pre_pr_validation_evidence_bundle(
        _projection(),
        plan,
        (changed,),
        expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID,
        expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
    )
    assert first.bundle_id != second.bundle_id


def test_pr_less_reconstruction_does_not_construct_projection(monkeypatch):
    from scripts.agent_os_execution_capabilities.approved_projection import GovernedProjectionEvidenceResult
    from scripts.agent_os_remote_validation.evidence_bundle import _canonical_bytes

    bundle = _bundle(_plan())
    data = serialize_validation_evidence_bundle(bundle)

    def refused_creation(*_args, **_kw):
        pytest.fail("Reconstruction must not construct approval/projection evidence")

    monkeypatch.setattr(GovernedProjectionEvidenceResult, "__init__", refused_creation)
    rebuilt = reconstruct_validation_evidence_bundle(data)
    assert _canonical_bytes(serialize_validation_evidence_bundle(rebuilt)) == _canonical_bytes(data)


def test_pr_less_requires_validation_only_plan():
    plan = _plan()
    wrong = replace(plan, subject=replace(plan.subject, execution_mode="production"))
    with pytest.raises(ValueError, match="validation-only"):
        _bundle(wrong)


@pytest.mark.parametrize("field,value,exception", [
    ("proposal_id", None, TypeError),
    ("repository_state_evidence_id", "", ValueError),
    ("merge_authorized", 0, TypeError),
])
def test_pr_less_reconstruction_rejects_untyped_or_missing_bindings(field, value, exception):
    data = serialize_validation_evidence_bundle(_bundle(_plan()))
    data[field] = value
    with pytest.raises(exception, match=field):
        reconstruct_validation_evidence_bundle(data)


@pytest.mark.parametrize("field,value", [("tested_sha", "7" * 40), ("base_branch", "different")])
def test_pr_less_serialize_rejects_independently_misbound_receipt_with_recomputed_digest(field, value):
    from scripts.agent_os_remote_validation.evidence_bundle import _bundle_payload, _semantic_digest
    from scripts.agent_os_remote_validation.selector import serialize_pre_pr_validation_plan

    bundle = _bundle(_plan())
    wrong = replace(bundle, **{field: value}, bundle_id="")
    body = _bundle_payload(replace(wrong, validation_plan=None))
    body["validation_plan"] = serialize_pre_pr_validation_plan(wrong.validation_plan)
    bogus_id = "validation-evidence-bundle:" + _semantic_digest("agent-os-validation-evidence-bundle:v1", body)
    with pytest.raises(ValueError, match=field):
        serialize_validation_evidence_bundle(replace(wrong, bundle_id=bogus_id))


@pytest.mark.parametrize("invalid", [False, 0.0, 1.0])
def test_pr_less_command_exit_is_exact_integer(invalid):
    data = serialize_validation_evidence_bundle(_bundle(_plan()))
    data["command_results"][0]["exit_code"] = invalid
    with pytest.raises(TypeError, match="exit_code"):
        reconstruct_validation_evidence_bundle(data)


def test_pr_less_builder_does_not_admit_unaccepted_projection():
    plan = _plan()
    observation = replace(_projection(), status="needs-decision", reason_codes=("worktree.indeterminate",))
    bundle = build_pre_pr_validation_evidence_bundle(
        observation, plan, (_result(plan),), expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID, expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z", completed_at="2026-09-08T17:00:01Z",
    )
    assert bundle.status == "needs-decision"
    assert bundle.reason_codes == ("projection.needs-decision",)


def test_pr_less_builder_checks_size_before_return(monkeypatch):
    from scripts.agent_os_remote_validation import pre_pr_evidence_bundle as module

    monkeypatch.setattr(module, "MAX_BUNDLE_SERIALIZED_BYTES", 128)
    with pytest.raises(ValueError, match="size limit"):
        _bundle(_plan())


def test_pr_less_builder_rejects_untyped_command_observation():
    plan = _plan()
    with pytest.raises(TypeError, match="SuppliedCommandResult"):
        build_pre_pr_validation_evidence_bundle(
            _projection(), plan, ({"status": "passed"},), expected_repository=_identity(),
            expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
            expected_proposal_id=PROPOSAL_ID, expected_repository_state_evidence_id=EVIDENCE_ID,
            runner_id="dev-validation:remote-validation",
            started_at="2026-09-08T17:00:00Z", completed_at="2026-09-08T17:00:01Z",
        )


@pytest.mark.parametrize("change,expected", [
    (lambda data: data["command_results"][0].pop("diagnostic_summary"), "command_result fields"),
    (lambda data: data["command_results"][0].update(extra=False), "command_result fields"),
    (lambda data: data["repository_identity"].update(owner=5), "owner"),
    (lambda data: data.update(unexpected={"authority": False}), "fields drifted"),
])
def test_pr_less_closed_payload_rejects_bad_nested_or_extra_field(change, expected):
    data = serialize_validation_evidence_bundle(_bundle(_plan()))
    change(data)
    with pytest.raises((TypeError, ValueError), match=expected):
        reconstruct_pre_pr_validation_evidence_bundle(data)


def test_pr_less_build_digest_excludes_bundle_id():
    from scripts.agent_os_remote_validation.evidence_bundle import _semantic_digest

    bundle = _bundle(_plan())
    payload = serialize_validation_evidence_bundle(bundle)
    bundle_id = payload.pop("bundle_id")
    assert bundle_id == "validation-evidence-bundle:" + _semantic_digest(
        "agent-os-validation-evidence-bundle:v1", payload
    )


def test_pr_less_cannot_serialize_wrong_result_with_fresh_bundle_digest():
    from scripts.agent_os_remote_validation.evidence_bundle import _bundle_payload, _semantic_digest
    from scripts.agent_os_remote_validation.selector import serialize_pre_pr_validation_plan

    bundle = _bundle(_plan())
    wrong = replace(bundle, command_results=(replace(bundle.command_results[0], command="different"),))
    body = _bundle_payload(replace(wrong, validation_plan=None))
    body["validation_plan"] = serialize_pre_pr_validation_plan(wrong.validation_plan)
    digest = "validation-evidence-bundle:" + _semantic_digest("agent-os-validation-evidence-bundle:v1", body)
    with pytest.raises(ValueError, match="command-mismatch"):
        serialize_validation_evidence_bundle(replace(wrong, bundle_id=digest))


def test_explicit_plan_has_same_subject_not_only_matching_reported_id(monkeypatch):
    from scripts.agent_os_remote_validation import pre_pr_evidence_bundle as module

    plan = _plan()
    bundle = _bundle(plan)
    from scripts.agent_os_remote_validation.evidence_bundle import _bundle_payload, _semantic_digest
    from scripts.agent_os_remote_validation.selector import serialize_pre_pr_validation_plan

    other = replace(plan, subject=replace(plan.subject, expected_changed_paths=()))
    monkeypatch.setattr(module, "pre_pr_validation_plan_id", lambda _: bundle.plan_id)
    body = _bundle_payload(replace(bundle, validation_plan=None))
    body["validation_plan"] = serialize_pre_pr_validation_plan(other)
    digest = "validation-evidence-bundle:" + _semantic_digest("agent-os-validation-evidence-bundle:v1", body)
    with pytest.raises(ValueError, match="supplied validation_plan"):
        serialize_pre_pr_validation_evidence_bundle(replace(bundle, bundle_id=digest), other)


def test_pr_less_reconstruction_cannot_turn_empty_result_into_pass():
    from scripts.agent_os_remote_validation.evidence_bundle import _semantic_digest

    payload = serialize_validation_evidence_bundle(_bundle(_plan()))
    payload.pop("bundle_id")
    payload["command_results"] = []
    payload["bundle_id"] = "validation-evidence-bundle:" + _semantic_digest(
        "agent-os-validation-evidence-bundle:v1", payload
    )
    with pytest.raises(ValueError, match="complete successful command evidence"):
        reconstruct_validation_evidence_bundle(payload)


def test_pr_less_reader_never_accepts_nonnull_pull_request():
    payload = serialize_validation_evidence_bundle(_bundle(_plan()))
    payload["pull_request"] = 17
    with pytest.raises(ValueError, match="pull_request must be null"):
        reconstruct_pre_pr_validation_evidence_bundle(payload)


@pytest.mark.parametrize("serialized", [False, True])
def test_pr_less_unverified_bundle_id_is_rejected(serialized):
    bundle = _bundle(_plan())
    if serialized:
        data = serialize_validation_evidence_bundle(bundle)
        data["bundle_id"] = "validation-evidence-bundle:" + "0" * 64
        with pytest.raises(ValueError, match="bundle ID mismatch"):
            reconstruct_validation_evidence_bundle(data)
    else:
        with pytest.raises(ValueError, match="bundle ID mismatch"):
            validation_evidence_bundle_id(replace(bundle, bundle_id="validation-evidence-bundle:bogus"))


def test_pr_less_separate_projection_binding_cannot_be_replaced():
    plan = _plan()
    observation = replace(_projection(), repository_identity=replace(_identity(), repository="wrong"))
    bundle = build_pre_pr_validation_evidence_bundle(
        observation, plan, (_result(plan),), expected_repository=_identity(),
        expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID, expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation",
        started_at="2026-09-08T17:00:00Z", completed_at="2026-09-08T17:00:01Z",
    )
    assert bundle.status == "invalid"
    assert bundle.reason_codes == ("projection.repository-mismatch",)
    assert reconstruct_validation_evidence_bundle(serialize_validation_evidence_bundle(bundle)) == bundle


def test_pr_less_no_missing_approval_id_even_on_in_memory_plan():
    plan = _plan()
    object.__setattr__(plan.subject, "approval_id", "")
    with pytest.raises(ValueError, match="approval_id"):
        _bundle(plan)


def test_pr_less_reader_oversize_fails_even_before_nested_plan(monkeypatch):
    from scripts.agent_os_remote_validation import pre_pr_evidence_bundle as module

    data = serialize_validation_evidence_bundle(_bundle(_plan()))
    monkeypatch.setattr(module, "MAX_BUNDLE_SERIALIZED_BYTES", 128)
    with pytest.raises(ValueError, match="size limit"):
        reconstruct_validation_evidence_bundle(data)


def test_pr_less_reader_uses_one_canonical_plan_decode(monkeypatch):
    from scripts.agent_os_remote_validation import pre_pr_evidence_bundle as module

    data = serialize_validation_evidence_bundle(_bundle(_plan()))
    original = module.deserialize_pre_pr_validation_plan
    decoded = []

    def record(value):
        decoded.append(value)
        return original(value)

    monkeypatch.setattr(module, "deserialize_pre_pr_validation_plan", record)
    bundle = reconstruct_validation_evidence_bundle(data)
    assert decoded == [data["validation_plan"]] and bundle.bundle_id == data["bundle_id"]


def build_with_test_overrides(**overrides):
    plan = _plan()
    args = dict(
        governed_projection=_projection(), validation_plan=plan, command_results=(_result(plan),),
        expected_repository=_identity(), expected_repository_evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
        expected_proposal_id=PROPOSAL_ID, expected_repository_state_evidence_id=EVIDENCE_ID,
        runner_id="dev-validation:remote-validation", started_at="2026-09-08T17:00:00Z",
        completed_at="2026-09-08T17:00:01Z",
    )
    args.update(overrides)
    return build_pre_pr_validation_evidence_bundle(**args)


@pytest.mark.parametrize("field,value,kind,code", [
    ("governed_projection", None, TypeError, "governed_projection"),
    ("validation_plan", {}, TypeError, "validation_plan"),
    ("expected_repository", None, TypeError, "repository_identity"),
    ("expected_repository_evidence_type", "branch-head", TypeError, "repository_evidence_type"),
    ("command_results", [], TypeError, "exact tuple"),
    ("expected_proposal_id", "", ValueError, "proposal_id"),
    ("expected_repository_state_evidence_id", "", ValueError, "repository_state_evidence_id"),
    ("runner_id", "space not an identifier", ValueError, "runner_id"),
])
def test_pr_less_builder_does_not_rescue_invalid_arguments(field, value, kind, code):
    with pytest.raises(kind, match=code):
        build_with_test_overrides(**{field: value})


@pytest.mark.parametrize("field,value,kind,code", [
    ("execution_authorized", True, ValueError, "execution_authorized must remain false"),
    ("command_results", {}, TypeError, "command_results must be a list"),
    ("command_results", [None], TypeError, "command_result must be an exact object"),
    ("repository_identity", None, TypeError, "repository_identity must be an exact object"),
    ("repository_evidence_type", 1, TypeError, "repository_evidence_type"),
    ("schema_name", "another", ValueError, "unsupported validation evidence bundle schema"),
    ("status", [], TypeError, "bundle status must be exact text"),
    ("status", "something-else", ValueError, "bundle status is invalid"),
    ("reason_codes", [1], TypeError, "reason_codes must be a list of exact strings"),
])
def test_pr_less_reader_rejects_forged_meta_fields(field, value, kind, code):
    payload = serialize_validation_evidence_bundle(_bundle(_plan()))
    payload[field] = value
    with pytest.raises(kind, match=code):
        reconstruct_pre_pr_validation_evidence_bundle(payload)


@pytest.mark.parametrize("field,value,kind", [("status", [], TypeError), ("command_ordinal", 0.0, TypeError)])
def test_pr_less_reader_refuses_noncanonical_receipt_types(field, value, kind):
    payload = serialize_validation_evidence_bundle(_bundle(_plan()))
    payload["command_results"][0][field] = value
    with pytest.raises(kind, match=field):
        reconstruct_pre_pr_validation_evidence_bundle(payload)


def test_pr_less_unknown_and_invalid_projection_never_pass():
    projection = replace(_projection(), status="stale", reason_codes=("worktree.dirty",))
    bundle = build_with_test_overrides(governed_projection=projection)
    assert bundle.status == "invalid" and bundle.reason_codes == ("projection.not-accepted",)
    assert not bundle.execution_authorized and not bundle.merge_authorized
    assert build_with_test_overrides(command_results=()).status == "incomplete"


def test_pr_less_canonical_bytes_detect_different_bytes_despite_equal_dicts():
    class CaseInsensitiveString(str):
        def __eq__(self, other):
            return isinstance(other, str) and self.casefold() == other.casefold()

        __hash__ = str.__hash__

    canonical = serialize_validation_evidence_bundle(_bundle(_plan()))
    raw = dict(canonical, repository_identity=dict(canonical["repository_identity"]))
    raw["repository_identity"]["owner"] = CaseInsensitiveString(raw["repository_identity"]["owner"].upper())
    # Direct object callers can provide scalar subclasses. An equal dictionary
    # is insufficient when its canonical JSON actually differs.
    from scripts.agent_os_remote_validation.evidence_bundle import _canonical_bytes

    assert raw == canonical
    assert _canonical_bytes(raw) != _canonical_bytes(canonical)
    with pytest.raises(ValueError, match="noncanonical"):
        reconstruct_validation_evidence_bundle(raw)


def test_pr_less_does_not_accept_untyped_plan_subject():
    plan = _plan()
    object.__setattr__(plan, "subject", None)
    with pytest.raises(TypeError, match="validation_plan.subject"):
        build_with_test_overrides(validation_plan=plan)


def test_pr_less_does_not_accept_untyped_mode():
    plan = _plan()
    object.__setattr__(plan.subject, "execution_mode", True)
    with pytest.raises(TypeError, match="execution_mode"):
        build_with_test_overrides(validation_plan=plan)


def test_pr_less_rejects_wrong_repository_slug_or_fork_type():
    with pytest.raises(ValueError, match="repository_identity"):
        build_with_test_overrides(expected_repository=replace(_identity(), repository="other"))
    with pytest.raises(TypeError, match="is_fork"):
        build_with_test_overrides(expected_repository=replace(_identity(), is_fork=0))


def test_pr_less_builder_preserves_invalid_timestamp_and_result_diagnostics():
    bundle = build_with_test_overrides(started_at="bad-time")
    assert "bundle.timestamp" in bundle.reason_codes and bundle.status == "invalid"
    plan = _plan()
    bundle = build_with_test_overrides(command_results=(replace(_result(plan), command="another"),))
    assert bundle.reason_codes == ("results.invalid",) and not bundle.command_results
    assert "result-0:command-mismatch" in bundle.details


def test_pr_less_reader_and_writer_require_exact_bundle_and_payload_objects():
    with pytest.raises(TypeError, match="ValidationEvidenceBundle"):
        serialize_pre_pr_validation_evidence_bundle(None)
    with pytest.raises(TypeError, match="exact dictionary"):
        reconstruct_pre_pr_validation_evidence_bundle(None)
    existing = _bundle(_plan())
    with pytest.raises(TypeError, match="bundle must carry"):
        serialize_pre_pr_validation_evidence_bundle(replace(existing, validation_plan=None), existing.validation_plan)
    with pytest.raises(TypeError, match="tested_sha"):
        serialize_pre_pr_validation_evidence_bundle(replace(existing, tested_sha=0))


@pytest.mark.parametrize("overrides", [
    {"command_results": ()},
    {"command_results": None},
    {"reason_codes": ("unsupported-success-label",)},
    {"details": ("unsupported-success-diagnostic",)},
    {"started_at": "not-a-time"},
    {"completed_at": "not-a-time"},
    {"started_at": "2026-09-08T17:00:02Z"},
])
def test_pr_less_no_pass_for_incomplete_success_evidence(overrides):
    bundle = _bundle(_plan())
    if overrides.get("command_results", False) is None:
        overrides = {"command_results": (replace(bundle.command_results[0], status="failed"),)}
    with pytest.raises(ValueError, match="complete successful command evidence"):
        serialize_validation_evidence_bundle(replace(bundle, **overrides))


def test_pr_less_bundle_wrong_type_and_plan_compatibility_are_independent():
    bundle = _bundle(_plan())
    with pytest.raises(TypeError, match="repository_evidence_type"):
        serialize_validation_evidence_bundle(replace(bundle, repository_evidence_type="branch-head"))
    with pytest.raises(ValueError, match="unsupported validation evidence bundle schema"):
        serialize_validation_evidence_bundle(replace(bundle, schema_version="7.0"))
    assert serialize_pre_pr_validation_evidence_bundle(bundle, replace(bundle.validation_plan)) == (
        serialize_validation_evidence_bundle(bundle)
    )


def test_pr_less_result_unknown_outcome_uses_shared_no_decision_semantics():
    plan = _plan()
    started = _result(plan)
    result = replace(started, status="unavailable", exit_code=None)
    bundle = build_with_test_overrides(command_results=(result,))
    assert (bundle.status, bundle.reason_codes) == ("needs-decision", ("results.unavailable",))
    assert reconstruct_validation_evidence_bundle(serialize_validation_evidence_bundle(bundle)) == bundle
