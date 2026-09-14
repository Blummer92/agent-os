import ast
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.pr_batch_merge_plan import (
    CANONICAL_BLOCKER_SCOPES,
    CANONICAL_MERGE_ADMISSION_STATUSES,
    CANONICAL_PR_STATES,
    PrBatchDisposition,
    PrBatchItemEvidence,
    PrBatchMergePlan,
    PrBatchPlanItem,
    build_pr_batch_merge_plan,
    normalize_finite_pr_targets,
)
from tests.agent_os_issue_acceptance.test_architecture_boundaries import _domain_matches

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "agent_os_issue_acceptance"
    / "pr_batch_merge_plan.py"
)


def ev(number, *, state="open", admission="applicable", blocker="none", head=None):
    return PrBatchItemEvidence(
        pull_request_number=number,
        head_sha=head or f"head-{number}",
        base_branch="main",
        state=state,
        merge_admission_status=admission,
        blocker_scope=blocker,
    )


def test_finite_ordered_list_is_accepted_and_duplicates_normalize():
    assert normalize_finite_pr_targets([101, 102, 101, 103]) == (101, 102, 103)
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101, 102, 101, 103],
        evidence=[ev(103), ev(101), ev(102)],
    )
    assert [item.pull_request_number for item in plan.items] == [101, 102, 103]
    assert all(item.disposition is PrBatchDisposition.CANDIDATE for item in plan.items)
    assert plan.merge_authorized is False
    assert plan.side_effects_performed is False


@pytest.mark.parametrize("targets", [[], ["*"], [0], [-1], [True]])
def test_empty_wildcard_or_unbounded_style_targets_are_rejected(targets):
    with pytest.raises(ValueError):
        normalize_finite_pr_targets(targets)


def test_terminal_pr_is_classified_without_mutation_authority():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, state="merged")],
    )
    assert plan.items[0].disposition is PrBatchDisposition.ALREADY_TERMINAL
    assert plan.items[0].merge_authorized is False


def test_changed_head_requires_new_evidence_not_old_plan_authority():
    first = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, head="head-a")],
    )
    assert first.items[0].observed_head_sha == "head-a"
    assert first.items[0].requires_pre_merge_reacquisition is True
    second = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101],
        evidence=[ev(101, head="head-b", admission="stale", blocker="item")],
    )
    assert second.items[0].disposition is PrBatchDisposition.ITEM_LOCAL_BLOCKED


def test_changed_main_is_explicit_plan_identity_and_requires_reacquisition():
    first = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102], evidence=[ev(101), ev(102)]
    )
    second = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-b",
        requested_pull_requests=[101, 102], evidence=[ev(101), ev(102)]
    )
    assert first.base_revision != second.base_revision
    assert all(item.requires_pre_merge_reacquisition for item in second.items)


def test_missing_or_ambiguous_merge_authority_is_item_local_blocked():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102],
        evidence=[ev(101, admission="needs-decision", blocker="item"), ev(102)],
    )
    assert [item.disposition for item in plan.items] == [
        PrBatchDisposition.ITEM_LOCAL_BLOCKED,
        PrBatchDisposition.CANDIDATE,
    ]
    assert plan.halt_remaining is False


def test_shared_blocker_halts_remaining_batch():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os", base_revision="main-a",
        requested_pull_requests=[101, 102, 103],
        evidence=[ev(101), ev(102, admission="blocked", blocker="shared"), ev(103)],
    )
    assert [item.pull_request_number for item in plan.items] == [101, 102]
    assert plan.items[-1].disposition is PrBatchDisposition.SHARED_BLOCKED
    assert plan.halt_remaining is True


def test_evidence_must_cover_exact_normalized_batch():
    with pytest.raises(ValueError):
        build_pr_batch_merge_plan(
            repository="Blummer92/agent-os", base_revision="main-a",
            requested_pull_requests=[101, 102], evidence=[ev(101)]
        )


def test_planner_is_registered_in_exactly_the_planning_domain():
    """A production module is unclassified until DOMAIN_RULES registers it.

    This planner is a planning-domain module. Pinning the domain keeps the
    dependency-direction rules that apply to it (no handoff/approval/mode/
    reporting imports) from being silently relaxed by a reclassification.
    """
    assert _domain_matches("pr_batch_merge_plan") == ["planning"]


def test_planner_imports_nothing_that_could_retrieve_or_mutate_state():
    """The module claims to be pure-local; prove it from the source, not the prose."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                pytest.fail("planning module must not import sibling package modules")
            if node.module:
                imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "dataclasses", "enum", "typing"}

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not called & {"open", "exec", "eval", "__import__"}


@pytest.mark.parametrize(
    "field, value",
    [
        ("merge_authorized", True),
        ("requires_pre_merge_reacquisition", False),
    ],
)
def test_plan_item_authority_constants_cannot_be_widened_by_a_caller(field, value):
    """`Literal[False]` is erased at runtime, so the constructor has to enforce it."""
    kwargs = {
        "sequence": 1,
        "pull_request_number": 101,
        "disposition": PrBatchDisposition.CANDIDATE,
        "observed_head_sha": "head-101",
        "observed_base_branch": "main",
        field: value,
    }
    with pytest.raises(ValueError, match=field):
        PrBatchPlanItem(**kwargs)


@pytest.mark.parametrize("field", ["merge_authorized", "side_effects_performed"])
def test_plan_authority_constants_cannot_be_widened_by_a_caller(field):
    kwargs = {
        "schema_version": "1.0",
        "repository": "Blummer92/agent-os",
        "base_revision": "main-a",
        "requested_pull_requests": (101,),
        "items": (),
        "halt_remaining": False,
        field: True,
    }
    with pytest.raises(ValueError, match=field):
        PrBatchMergePlan(**kwargs)


def test_truthy_non_bool_never_satisfies_an_authority_constant():
    """Identity, not truthiness: `1 == False` style coercion must not slip through."""
    with pytest.raises(ValueError, match="requires_pre_merge_reacquisition"):
        PrBatchPlanItem(
            sequence=1,
            pull_request_number=101,
            disposition=PrBatchDisposition.CANDIDATE,
            observed_head_sha="head-101",
            observed_base_branch="main",
            requires_pre_merge_reacquisition=1,
        )


def test_every_disposition_still_reports_no_merge_authority():
    plan = build_pr_batch_merge_plan(
        repository="Blummer92/agent-os",
        base_revision="main-a",
        requested_pull_requests=[101, 102, 103],
        evidence=[
            ev(101),
            ev(102, state="merged"),
            ev(103, admission="invalid", blocker="item"),
        ],
    )
    assert {item.disposition for item in plan.items} == {
        PrBatchDisposition.CANDIDATE,
        PrBatchDisposition.ALREADY_TERMINAL,
        PrBatchDisposition.ITEM_LOCAL_BLOCKED,
    }
    assert plan.merge_authorized is False
    assert plan.side_effects_performed is False
    assert all(item.merge_authorized is False for item in plan.items)
    assert all(item.requires_pre_merge_reacquisition is True for item in plan.items)


@pytest.mark.parametrize(
    "field, value",
    [
        ("state", "BOGUS"),
        ("state", "Open"),
        ("state", ""),
        ("state", None),
        ("merge_admission_status", "approved"),
        ("merge_admission_status", "APPLICABLE"),
        ("merge_admission_status", None),
        ("blocker_scope", "batch"),
        ("blocker_scope", "None"),
        ("blocker_scope", None),
    ],
)
def test_non_canonical_evidence_fails_closed_instead_of_becoming_a_candidate(field, value):
    """Unknown vocabulary must never normalize into a merge-eligible disposition."""
    kwargs = {
        "pull_request_number": 101,
        "head_sha": "head-101",
        "base_branch": "main",
        "state": "open",
        "merge_admission_status": "applicable",
        field: value,
    }
    with pytest.raises(ValueError, match=field):
        PrBatchItemEvidence(**kwargs)


def test_canonical_vocabularies_match_the_documented_contract():
    assert CANONICAL_PR_STATES == frozenset({"open", "closed", "merged"})
    assert CANONICAL_MERGE_ADMISSION_STATUSES == frozenset(
        {"applicable", "blocked", "stale", "needs-decision", "invalid"}
    )
    assert CANONICAL_BLOCKER_SCOPES == frozenset({"none", "item", "shared"})
