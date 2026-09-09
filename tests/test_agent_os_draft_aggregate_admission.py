from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_draft_aggregate_profile_requires_explicit_final_candidate_admission():
    """A Draft PR still defers the automatic aggregate to explicit admission.

    The admission condition no longer consults the validation-plan profile
    (#2132): a Ready PR runs the authoritative aggregate whatever its profile,
    because a *skipped* required job is indistinguishable from a passing one to
    branch protection. Draft deferral is unchanged, and remains the only way
    the automatic aggregate is withheld.
    """
    content = _workflow()
    assert (
        "if: ${{ always() && (github.event_name != 'pull_request' || "
        "github.event.pull_request.draft == false) }}"
    ) in content
    assert "Admit exact-head Draft final candidate" in content
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in content


def test_draft_open_and_synchronize_keep_plan_but_cannot_auto_run_aggregate():
    content = _workflow()
    trigger = content[content.index("pull_request:") : content.index("push:")]
    assert "opened" in trigger
    assert "reopened" in trigger
    assert "synchronize" in trigger
    assert "Run validation plan" in content
    assert "github.event.pull_request.draft == false" in content


def test_exact_head_final_candidate_contract_remains_fail_closed():
    content = _workflow()
    assert 'if [ "$current_head" != "$EXPECTED_HEAD_SHA" ]' in content
    assert "stale final-candidate request" in content
    assert 'if [ "$GITHUB_SHA" != "$EXPECTED_HEAD_SHA" ]' in content
    assert "final-candidate dispatch SHA $GITHUB_SHA does not match admitted candidate $EXPECTED_HEAD_SHA" in content


def test_push_to_main_and_authoritative_aggregate_identity_are_preserved():
    content = _workflow()
    push = content[content.index("push:") : content.index("workflow_dispatch:")]
    assert "main" in push
    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content
    assert content.count("./scripts/validate-all.sh") == 1


def test_aggregate_profile_summary_states_draft_deferral():
    content = _workflow()
    assert (
        "Aggregate profile selected; Draft PR events defer authoritative aggregate "
        "validation to explicit exact-head final-candidate admission."
    ) in content
