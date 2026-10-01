from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROFILE_SCHEMA = ROOT / "03_Templates/external-repository-profile.v1alpha1.schema.json"
REGISTRY_SCHEMA = ROOT / "03_Templates/external-repository-registry.v1alpha1.schema.json"
REGISTRY = ROOT / "04_Registry/external-repositories.yml"
STANDARD = ROOT / "01_Shared_Standards/github/external-repository-governance.md"
FIXTURES = ROOT / "tests/fixtures/external_repository_governance"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_profile_schema_is_strict_versioned_and_non_authorizing():
    schema = load_json(PROFILE_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "agent-os://external-repository-profile/v1alpha1"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["apiVersion"]["const"] == "agent-os.external-repository-governance/v1alpha1"
    assert schema["properties"]["kind"]["const"] == "ExternalRepositoryProfile"
    assert set(schema["properties"]) == {"apiVersion", "kind", "governanceDocuments"}
    roles = schema["properties"]["governanceDocuments"]
    assert roles["maxProperties"] == 20
    assert "authoriz" in roles["propertyNames"]["pattern"]


def test_profile_safe_path_contract_rejects_lexically_unsafe_paths():
    schema = load_json(PROFILE_SCHEMA)
    pattern = schema["$defs"]["safeRelativePath"]["pattern"]
    assert re.fullmatch(pattern, "AGENTS.md")
    assert re.fullmatch(pattern, "docs/source-of-truth.md")
    for value in ("/etc/passwd", "../AGENTS.md", "docs/../AGENTS.md", "docs//policy.md", r"docs\\policy.md"):
        assert re.fullmatch(pattern, value) is None


def test_registry_schema_owns_central_identity_lifecycle_and_routing_only():
    schema = load_json(REGISTRY_SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "agent-os://external-repository-registry/v1alpha1"
    assert schema["additionalProperties"] is False
    record = schema["$defs"]["repositoryRecord"]
    assert record["additionalProperties"] is False
    assert set(record["required"]) == {"registryId", "repository", "admission", "lifecycle", "profilePath", "contractVersion", "routing"}
    assert "generatedStatus" not in record["properties"]
    assert "approval" not in record["properties"]
    assert "authorization" not in record["properties"]
    assert record["properties"]["contractVersion"]["const"] == "agent-os.external-repository-governance/v1alpha1"


def test_initial_registry_is_specification_only_and_empty():
    text = REGISTRY.read_text(encoding="utf-8")
    assert "apiVersion: agent-os.external-repository-governance-registry/v1alpha1" in text
    assert "kind: ExternalRepositoryRegistry" in text
    assert "repositories: []" in text


def test_fixtures_cover_positive_unknown_path_authority_and_yaml_feature_cases():
    valid = (FIXTURES / "valid-profile.yml").read_text(encoding="utf-8")
    assert "apiVersion: agent-os.external-repository-governance/v1alpha1" in valid
    assert "governanceDocuments:" in valid
    assert "generatedStatus: pass" in (FIXTURES / "invalid-unknown-field.yml").read_text(encoding="utf-8")
    assert "../AGENTS.md" in (FIXTURES / "invalid-unsafe-path.yml").read_text(encoding="utf-8")
    assert "productionAuthorized: true" in (FIXTURES / "invalid-authority-field.yml").read_text(encoding="utf-8")
    yaml_features = (FIXTURES / "invalid-yaml-features.yml").read_text(encoding="utf-8")
    assert "&defaults" in yaml_features
    assert "*defaults" in yaml_features
    assert "<<:" in yaml_features
    assert yaml_features.count("repository-policy:") >= 3


def test_standard_pins_fail_closed_bounds_results_compatibility_and_downstream_owner():
    text = STANDARD.read_text(encoding="utf-8")
    for required in (
        "65,536 UTF-8 bytes",
        "12 levels",
        "100 items",
        "duplicate mapping keys",
        "aliases, anchors, merge keys",
        "unsupported `apiVersion`",
        "pass",
        "warning",
        "fail",
        "manual-review",
        "infrastructure-error",
        "90 days",
        "two Agent OS repository releases",
        "#581 must consume these schemas",
    ):
        assert required in text


def test_module_version_and_changelog_register_erg1():
    module_map = (ROOT / "04_Registry/module-version-map.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "| External Repository Governance | 0.2.0 |" in module_map
    assert "**External Repository Governance** `0.2.0`" in module_map
    assert "ERG1 (#580)" in changelog
    assert "ERG2 (#581)" in changelog


def test_standard_registers_erg2_validator():
    text = (
        ROOT / "01_Shared_Standards/github/external-repository-governance.md"
    ).read_text(encoding="utf-8")
    assert "Version: 0.2.0" in text
    assert "Validator issue: #581" in text
    for required in (
        "scripts/agent_os_external_repository_governance/validator.py",
        "scripts/erg2-validate",
        "authorizes nothing",
        "infrastructure-error",
    ):
        assert required in text
