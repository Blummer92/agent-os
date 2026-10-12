"""#3404: Renovate groups coupled dependencies without breaking validation identities.

The Vitest 5.0.3 PR bundled an unrelated MCP range from a stale branch because
every nested minor/patch update shared one "nested minor/patch" group, and the
Node engine widening shared scope with the dependency update. The coupled sets
(vitest <-> fixed runner identity, mcp <-> runtime/dependency parity, node
engines <-> fixed Node runtime identity) now each own a named Renovate group.
These tests prove the groups exist, the coupled packages are excluded from the
residual group, and every validation identity the grouping touches is unchanged
and still aligned with the pinned declarations.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
SCHEDULER_SRC = ROOT / "08_Tooling" / "workflow-scheduler" / "src"
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.governance import dev_validation
from workflow_scheduler.governance import dev_validation_gce
from workflow_scheduler.governance import dev_validation_profiles

RENOVATE_CONFIG = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
PACKAGE = ROOT / dev_validation.PPUX_VALIDATION_PACKAGE_DIR
CAPTURE_PACKAGE = ROOT / "08_Tooling" / "instructional-materials-coach" / "capture"
EXECUTION_SERVICE_PYPROJECT = (
    ROOT / "08_Tooling" / "agent-os-execution-service" / "pyproject.toml"
)

COUPLED_GROUP_NAMES = ("vitest", "mcp", "node")


def _rules_by_group() -> dict[str, dict]:
    rules = {}
    for rule in RENOVATE_CONFIG["packageRules"]:
        group = rule.get("groupName")
        if group is not None:
            rules[group] = rule
    return rules


def _rule_by_group(name: str) -> dict:
    return _rules_by_group()[name]


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def test_renovate_config_is_valid_json_with_package_rules() -> None:
    assert isinstance(RENOVATE_CONFIG["packageRules"], list)
    assert RENOVATE_CONFIG["packageRules"]


def test_coupled_groups_exist_with_narrow_matchers() -> None:
    vitest_rule = _rule_by_group("vitest")
    assert _as_list(vitest_rule["matchManagers"]) == ["npm"]
    assert _as_list(vitest_rule["matchPackageNames"]) == ["vitest"]

    mcp_rule = _rule_by_group("mcp")
    assert set(_as_list(mcp_rule["matchManagers"])) == {"pep621", "pip_requirements"}
    assert _as_list(mcp_rule["matchPackageNames"]) == ["mcp"]

    node_rule = _rule_by_group("node")
    assert _as_list(node_rule["matchManagers"]) == ["node"]

    for name in COUPLED_GROUP_NAMES:
        rule = _rule_by_group(name)
        assert "groupName" in rule and rule["groupName"] == name


def test_residual_group_excludes_the_coupled_packages() -> None:
    residual = _rule_by_group("nested minor/patch")
    assert set(_as_list(residual["excludePackageNames"])) >= set(COUPLED_GROUP_NAMES)


def test_major_updates_still_carry_the_needs_decision_label() -> None:
    major_rules = [
        rule
        for rule in RENOVATE_CONFIG["packageRules"]
        if "major" in _as_list(rule.get("matchUpdateTypes", []))
    ]
    assert major_rules
    assert any("status:needs-decision" in rule.get("labels", []) for rule in major_rules)


def test_picture_perfect_identity_is_unchanged_and_matches_the_vitest_pin() -> None:
    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    pinned = manifest["devDependencies"]["vitest"]
    assert pinned == dev_validation_gce.DEV_VALIDATION_VITEST_VERSION

    profile = dev_validation_profiles.PROFILE_CATALOG["picture-perfect"]
    assert profile.profile_id == "picture-perfect"
    assert profile.runtime_id == f"node22-vitest-{pinned}"

    assert (
        dev_validation_profiles.PROFILE_ALIASES["ppux-picture-perfect-ts-vitest"]
        == "picture-perfect"
    )
    assert dev_validation_profiles.canonical_profile_id("ppux-picture-perfect-ts-vitest") == (
        "picture-perfect"
    )


def test_host_runner_still_pins_the_same_vitest_and_node_identity() -> None:
    pinned = dev_validation_gce.DEV_VALIDATION_VITEST_VERSION
    source = dev_validation_gce._HOST_RUNNER_SOURCE
    assert f"v!=='{pinned}'" in source
    assert "process.versions.node.startsWith('22.')" in source
    assert (
        dev_validation_gce.DEV_VALIDATION_NODE
        == "/usr/local/libexec/agent-os-dev-validation-node"
    )


def test_node_engines_identity_is_unchanged_across_coupled_packages() -> None:
    for directory in (CAPTURE_PACKAGE, PACKAGE):
        manifest = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        assert manifest["engines"]["node"] == ">=22.12 <25"


def test_mcp_declarations_stay_coupled_across_package_surfaces() -> None:
    payload = tomllib.loads(EXECUTION_SERVICE_PYPROJECT.read_text(encoding="utf-8"))
    nested = [
        Requirement(raw)
        for raw in payload["project"]["dependencies"]
        if Requirement(raw).name == "mcp"
    ]
    assert len(nested) == 1

    root_lines = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    root = []
    for line in root_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "-")):
            continue
        requirement = Requirement(stripped)
        if requirement.name == "mcp":
            root.append(requirement)
    assert len(root) == 1
    assert str(nested[0].specifier) == str(root[0].specifier)
