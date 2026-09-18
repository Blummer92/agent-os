from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITE = ROOT / "00_Governance/write-authorization-policy.md"
EXCLUDED = ROOT / "01_Shared_Standards/github/excluded-surface-baseline.md"
PROTECTED = ROOT / "01_Shared_Standards/github/protected-branch-governance.md"
SAFE = ROOT / "01_Shared_Standards/github/safe-implementation-lane.md"
GITHUB = ROOT / "02_Agent_Overlays/github-service-agent.md"
ADAPTER = ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/adapters/github_ruleset_admin_adapter.py"
CALLER = ROOT / "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/github_ruleset_admin_gce.py"


def normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_exact_authorization_does_not_require_second_admin_executor() -> None:
    write = normalized(WRITE)
    excluded = normalized(EXCLUDED)
    protected = normalized(PROTECTED)
    safe = normalized(SAFE)
    github = normalized(GITHUB)

    assert "authority requirement, not a requirement to use a second execution identity or admin framework" in write
    assert "does not require a second execution identity or a generic admin-capable surface" in excluded
    assert "does not by itself require a second execution identity" in protected
    # The lane document backticks the term, matching how it marks `continue`,
    # `next step` and `keep going` in the same paragraph.
    assert "`separately authorized` does not imply a second executor" in safe
    assert "do not require or invent a second admin agent/surface solely because the target is protected" in github


def test_finite_protected_setting_contract_preserves_fail_closed_invariants() -> None:
    contract = " ".join((normalized(WRITE), normalized(EXCLUDED), normalized(PROTECTED)))
    for phrase in (
        "fresh pre-state",
        "fail-closed",
        "canonical readback",
        "bounded rollback",
        "fixed target",
    ):
        assert phrase in contract

    assert "generic ruleset" in contract
    assert "credentials" in contract
    assert "IAM" in contract


def test_2234_ruleset_admin_path_remains_fixed_and_content_bound() -> None:
    adapter = normalized(ADAPTER)
    caller = normalized(CALLER)

    for literal in (
        'REPOSITORY = "Blummer92/agent-os"',
        "RULESET_ID = 19123362",
        'REQUIRED_CONTEXT = "Run aggregate validation"',
        "AUTHORIZATION_ISSUE = 1883",
        "expected_prestate_sha256",
        "unsupported request fields",
        "ruleset pre-state moved; mutation refused",
        "ruleset read-back did not converge",
    ):
        assert literal in adapter

    assert "only caller-supplied value is the fresh content-bound pre-state digest" in caller
    assert 'owner="GitHub Service Agent"' in caller


def test_arbitrary_protected_setting_authority_remains_blocked() -> None:
    excluded = normalized(EXCLUDED)
    protected = normalized(PROTECTED)
    assert "Arbitrary ruleset/branch-protection administration" in excluded
    assert "must not accept arbitrary API paths, commands, ruleset IDs, check names" in protected
