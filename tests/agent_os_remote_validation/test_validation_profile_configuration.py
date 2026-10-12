from pathlib import Path

from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan


ROOT = Path(__file__).resolve().parents[2]
RULES = load_rule_map()


def _input(path: str) -> SelectionInput:
    return SelectionInput(
        repository="Blummer92/agent-os",
        pull_request=1271,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(path,),
    )


def test_every_declared_aggregate_path_exists_in_repository() -> None:
    for path in RULES["aggregate_paths"]:
        assert (ROOT / path).is_file(), f"aggregate path does not exist: {path}"


def test_every_declared_aggregate_prefix_resolves_to_a_real_surface() -> None:
    for prefix in RULES["aggregate_prefixes"]:
        target = ROOT / prefix
        if prefix.endswith("/"):
            assert target.is_dir(), f"aggregate prefix does not exist: {prefix}"
        else:
            assert target.is_file(), f"aggregate prefix does not exist: {prefix}"


def test_every_declared_focused_rule_surface_exists_in_repository() -> None:
    for rule in RULES["focused_rules"]:
        for prefix in rule.get("prefixes", []):
            target = ROOT / prefix
            if prefix.endswith("/"):
                assert target.is_dir(), (
                    f"focused rule {rule['name']!r} prefix does not exist: {prefix}"
                )
            else:
                assert target.is_file(), (
                    f"focused rule {rule['name']!r} prefix does not exist: {prefix}"
                )
        for exact_path in rule.get("exact_paths", []):
            assert (ROOT / exact_path).is_file(), (
                f"focused rule {rule['name']!r} exact path does not exist: {exact_path}"
            )


def test_requirements_dev_selects_aggregate_without_changing_aggregate_identity() -> None:
    plan = select_validation_plan(_input("requirements-dev.txt"), RULES)

    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)


def test_root_changelog_is_documentation_not_manual_review() -> None:
    plan = select_validation_plan(_input("CHANGELOG.md"), RULES)
    assert plan.profile == "static"
    assert plan.reason_codes == ("profile.documentation-static",)


def test_standards_registry_and_root_changelog_are_static() -> None:
    subject = _input("CHANGELOG.md")
    subject = SelectionInput(
        repository=subject.repository,
        pull_request=subject.pull_request,
        base_sha=subject.base_sha,
        head_sha=subject.head_sha,
        changed_files=(
            "01_Shared_Standards/github/issue-lifecycle-standard.md",
            "04_Registry/responsibility-matrix.md",
            "CHANGELOG.md",
        ),
    )
    plan = select_validation_plan(subject, RULES)
    assert plan.profile == "static"
    assert plan.reason_codes == ("profile.documentation-static",)


def test_root_changelog_does_not_weaken_code_or_unknown_path_handling() -> None:
    subject = _input("CHANGELOG.md")
    for paths, expected_profile in (
        (("CHANGELOG.md", "scripts/agent_os_remote_validation/selector.py"), "focused"),
        (("CHANGELOG.md", "tests/agent_os_remote_validation/test_selector.py"), "focused"),
        (("CHANGELOG.md", "scripts/unmapped_example.py"), "aggregate"),
        (("CHANGELOG.md", "unmapped-policy.txt"), "manual-review"),
    ):
        value = SelectionInput(
            repository=subject.repository,
            pull_request=subject.pull_request,
            base_sha=subject.base_sha,
            head_sha=subject.head_sha,
            changed_files=paths,
        )
        plan = select_validation_plan(value, RULES)
        assert plan.profile == expected_profile, (paths, plan.reason_codes)
