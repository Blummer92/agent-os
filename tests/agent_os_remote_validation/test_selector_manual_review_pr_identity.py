from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan


def test_negative_pr_identity_fails_closed_to_safe_manual_review_sentinel():
    plan = select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=-1,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=("README.md",),
        ),
        load_rule_map(),
    )
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("metadata.malformed",)
    assert plan.pull_request == 0
