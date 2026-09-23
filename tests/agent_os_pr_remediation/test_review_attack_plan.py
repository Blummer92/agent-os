from scripts.agent_os_pr_remediation.review_attack_plan import build_review_attack_plan
from scripts.agent_os_pr_remediation.review_evidence import ReviewDepth, ReviewRiskEvidence, build_review_evidence_packet


def _risk(name: str) -> ReviewRiskEvidence:
    return ReviewRiskEvidence(name, (f"historical:{name}",))


def _packet(*risks: str, head: str = "b" * 40, depth: ReviewDepth = ReviewDepth.ADVERSARIAL):
    return build_review_evidence_packet(
        repository="Blummer92/agent-os", issue_number=1584, pr_number=1600,
        base_sha="a" * 40, head_sha=head, metadata_fingerprint="c" * 64,
        objective="Produce deterministic risk-specific Review Attack Plans.",
        acceptance_criteria=["stable attack ids"],
        allowed_paths=["scripts/agent_os_pr_remediation/"], forbidden_paths=[".github/workflows/"],
        non_goals=["no provider execution"], authorization_ceiling=["no-external-write"],
        changed_files=["scripts/agent_os_pr_remediation/review_evidence.py"], bounded_diff="@@ bounded @@",
        changed_contracts=["review-evidence-v1"], dependency_changes=[], workflow_changes=[],
        risk_evidence=[_risk(name) for name in risks], validation_profiles=["focused"],
        validation_results=["focused:pass"], exact_tested_sha=head,
        failed_finding_ids=[], repaired_finding_ids=[], unresolved_finding_ids=[],
        prior_reviewed_head="a" * 40, paths_changed_since_review=["scripts/agent_os_pr_remediation/review_evidence.py"],
        activated_references=["CRH1"], review_depth=depth,
    )


def _reasons(plan):
    return {reason for attack in plan.required_attacks for reason in attack.reason_codes}


def test_parser_and_authorization_change_gets_both_families_and_distinct_authorization_attacks():
    plan = build_review_attack_plan(_packet("parser", "authorization"))
    families = {attack.attack_family for attack in plan.required_attacks}
    assert families == {"parser", "authorization"}
    authorization = [attack for attack in plan.required_attacks if attack.attack_family == "authorization"]
    assert len(authorization) == 3
    assert len({attack.attack_id for attack in authorization}) == 3


def test_workflow_authority_replays_false_green_wrong_sha_and_stale_evidence_defects():
    plan = build_review_attack_plan(_packet("workflow-ci-authority"))
    reasons = _reasons(plan)
    assert "workflow-transport-vs-semantic" in reasons  # #1564 false green
    assert "workflow-wrong-sha" in reasons
    assert "workflow-stale-conflicting-evidence" in reasons


def test_state_machine_replays_illegal_partial_and_repeated_repair_cases():
    plan = build_review_attack_plan(_packet("state-machine", "retry-idempotency-reconciliation"))
    reasons = _reasons(plan)
    assert {"state-illegal-transition", "state-partial-effect", "state-retry-idempotency"} <= reasons


def test_ordinary_normal_review_does_not_inflate_to_adversarial_plan():
    plan = build_review_attack_plan(_packet(head="b" * 40, depth=ReviewDepth.NORMAL))
    assert plan.required_attacks == ()
    assert plan.manual_review_reasons == ()


def test_duplicate_risk_inputs_and_input_order_are_deterministic():
    first = build_review_attack_plan(_packet("parser", "authorization", "parser"))
    second = build_review_attack_plan(_packet("authorization", "parser"))
    assert first.plan_id == second.plan_id
    assert [a.attack_id for a in first.required_attacks] == [a.attack_id for a in second.required_attacks]


def test_manual_conflicting_risk_fails_closed_without_attack_reduction():
    plan = build_review_attack_plan(_packet("conflicting-evidence", depth=ReviewDepth.MANUAL))
    assert plan.required_attacks == ()
    assert plan.manual_review_reasons


def test_unknown_risk_fails_closed_manual():
    plan = build_review_attack_plan(_packet("unknown-future-risk"))
    assert plan.required_attacks == ()
    assert plan.manual_review_reasons == ("unknown-risk-class:unknown-future-risk",)


def test_same_risk_on_different_head_has_distinct_plan_and_attack_identity():
    first = build_review_attack_plan(_packet("parser", head="b" * 40))
    second = build_review_attack_plan(_packet("parser", head="d" * 40))
    assert first.plan_id != second.plan_id
    assert {a.attack_id for a in first.required_attacks}.isdisjoint({a.attack_id for a in second.required_attacks})


def test_historical_parser_first_match_defect_selects_ambiguity_attack():
    plan = build_review_attack_plan(_packet("parser"))
    assert "parser-ambiguity-first-match" in _reasons(plan)


def test_authorization_evidence_confusion_selects_non_authority_attack():
    plan = build_review_attack_plan(_packet("authorization"))
    assert "authorization-evidence-not-authority" in _reasons(plan)


def test_architecture_plan_reuses_supplied_contract_and_surface_identity():
    plan = build_review_attack_plan(_packet("architecture-ownership-interface"))
    attack = next(a for a in plan.required_attacks if a.attack_family == "architecture")
    assert "scripts/agent_os_pr_remediation/review_evidence.py" in attack.affected_surface_refs
    assert "review-evidence-v1" in attack.affected_surface_refs


def test_all_plan_authority_fields_remain_false():
    plan = build_review_attack_plan(_packet("parser"))
    assert plan.execution_authorized is False
    assert plan.merge_authorized is False
    assert plan.closure_authorized is False
    assert plan.readiness_authorized is False
    assert plan.production_authorized is False
    assert plan.protected_setting_authorized is False
    assert plan.external_write_authorized is False
    assert plan.side_effects_performed is False
