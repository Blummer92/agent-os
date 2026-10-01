"""ERG2 offline validator tests (#581 consumes the #580 contract).

Every negative fixture pins one fail-closed behavior required by the #580
standard. Tests assert the failing *check name*, not just the verdict, so a
fixture that fails for the wrong reason is caught.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from agent_os_external_repository_governance import validate_erg_document
from agent_os_external_repository_governance.models import ErgVerdict

REPO_ROOT = Path(__file__).resolve().parents[2]
ERG2 = REPO_ROOT / "tests" / "fixtures" / "external_repository_governance" / "erg2"
ERG1 = REPO_ROOT / "tests" / "fixtures" / "external_repository_governance"

EXPECTED_VERDICTS = {
    # (fixture, expected verdict, check that must carry the non-pass verdict)
    "profile.unknown-field.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "profile.duplicate-key.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.merge-key.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.anchor-alias.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.directive.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.multi-document.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.non-string-key.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.float-value.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.timestamp-value.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.binary-value.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.unsafe-absolute-path.yml": (ErgVerdict.FAIL, "declared-path-safety"),
    "profile.unsafe-dotdot-path.yml": (ErgVerdict.FAIL, "declared-path-safety"),
    "profile.unsafe-backslash-path.yml": (ErgVerdict.FAIL, "declared-path-safety"),
    "profile.overlong-path.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "profile.empty-roles.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "profile.too-many-roles.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "profile.too-many-items.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.too-deep.yml": (ErgVerdict.FAIL, "strict-yaml-input-bounds"),
    "profile.wrong-version.yml": (ErgVerdict.FAIL, "contract-identity"),
    "profile.wrong-kind.yml": (ErgVerdict.FAIL, "contract-identity"),
    "profile.non-mapping-document.yml": (ErgVerdict.FAIL, "contract-identity"),
    "registry.valid.yml": (ErgVerdict.PASS, None),
    "registry.lifecycle-states.yml": (ErgVerdict.PASS, None),
    "registry.tombstone.yml": (ErgVerdict.PASS, None),
    "registry.duplicate-registry-id.yml": (ErgVerdict.FAIL, "registry-admission-policy"),
    "registry.duplicate-repository.yml": (ErgVerdict.FAIL, "registry-admission-policy"),
    "registry.alias-collision.yml": (ErgVerdict.FAIL, "registry-admission-policy"),
    "registry.alias-alias-collision.yml": (ErgVerdict.FAIL, "registry-admission-policy"),
    "registry.unsafe-profile-path.yml": (ErgVerdict.FAIL, "registry-admission-policy"),
    "registry.record-unknown-field.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "registry.unknown-field.yml": (ErgVerdict.FAIL, "schema-conformance"),
    "registry.wrong-version.yml": (ErgVerdict.FAIL, "contract-identity"),
}


@pytest.mark.parametrize(
    "fixture,expected",
    sorted(EXPECTED_VERDICTS.items()),
    ids=sorted(EXPECTED_VERDICTS),
)
def test_erg2_fixture_verdicts(fixture, expected):
    expected_verdict, failing_check = expected
    text = (ERG2 / fixture).read_text(encoding="utf-8")
    report = validate_erg_document(text, source=fixture, repo_root=REPO_ROOT)
    assert report.verdict is expected_verdict, (
        f"{fixture}: expected {expected_verdict.value}, got {report.verdict.value}; "
        f"checks={[ (c.name, c.verdict.value, c.detail) for c in report.checks ]}"
    )
    if failing_check is not None:
        matched = [c for c in report.checks if c.name == failing_check]
        assert matched, f"{fixture}: no {failing_check} check present"
        assert any(c.verdict is ErgVerdict.FAIL for c in matched), (
            f"{fixture}: {failing_check} did not fail"
        )
    # Every report is evidence only.
    assert report.to_dict()["authorizes"] == "nothing"


def test_erg2_valid_profile_passes():
    text = (ERG1 / "valid-profile.yml").read_text(encoding="utf-8")
    report = validate_erg_document(text, source="valid-profile.yml", repo_root=REPO_ROOT)
    assert report.verdict is ErgVerdict.PASS
    assert report.document_kind == "ExternalRepositoryProfile"
    assert report.contract_version == "agent-os.external-repository-governance/v1alpha1"
    assert all(c.verdict is ErgVerdict.PASS for c in report.checks)


def test_erg2_erg1_invalid_fixtures_still_fail():
    for fixture in (
        "invalid-authority-field.yml",
        "invalid-unknown-field.yml",
        "invalid-unsafe-path.yml",
        "invalid-yaml-features.yml",
    ):
        text = (ERG1 / fixture).read_text(encoding="utf-8")
        report = validate_erg_document(text, source=fixture, repo_root=REPO_ROOT)
        assert report.verdict is ErgVerdict.FAIL, fixture


def test_erg2_deterministic():
    text = (ERG2 / "registry.duplicate-registry-id.yml").read_text(encoding="utf-8")
    first = validate_erg_document(text, source="x", repo_root=REPO_ROOT).to_dict()
    second = validate_erg_document(text, source="x", repo_root=REPO_ROOT).to_dict()
    assert first == second


def test_erg2_report_serializes_with_stdlib_json():
    text = (ERG2 / "registry.valid.yml").read_text(encoding="utf-8")
    report = validate_erg_document(text, source="registry.valid.yml", repo_root=REPO_ROOT)
    payload = json.dumps(report.to_dict(), sort_keys=True)
    assert json.loads(payload)["verdict"] == "pass"


def test_erg2_unreadable_schema_dir_is_infrastructure_error(tmp_path):
    report = validate_erg_document(
        "apiVersion: x\n",
        source="x",
        schema_dir=str(tmp_path / "missing"),
    )
    assert report.verdict is ErgVerdict.INFRASTRUCTURE_ERROR
    assert report.checks[0].name == "schema-availability"


def test_erg2_symlink_escape_fails(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.md").write_text("x", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    os.symlink(str(outside), repo / "link")
    text = (
        "apiVersion: agent-os.external-repository-governance/v1alpha1\n"
        "kind: ExternalRepositoryProfile\n"
        "governanceDocuments:\n"
        "  docs: link/evil.md\n"
    )
    report = validate_erg_document(text, source="symlink", repo_root=repo)
    assert report.verdict is ErgVerdict.FAIL
    assert any(
        c.name == "declared-path-safety" and c.verdict is ErgVerdict.FAIL
        for c in report.checks
    )


def test_erg2_symlink_inside_root_passes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "real.md").write_text("x", encoding="utf-8")
    os.symlink(str(repo / "docs"), repo / "alias")
    text = (
        "apiVersion: agent-os.external-repository-governance/v1alpha1\n"
        "kind: ExternalRepositoryProfile\n"
        "governanceDocuments:\n"
        "  docs: alias/real.md\n"
    )
    report = validate_erg_document(text, source="symlink-ok", repo_root=repo)
    assert report.verdict is ErgVerdict.PASS


def test_erg2_infrastructure_error_never_converts_to_policy():
    report = validate_erg_document("x", source="x", schema_dir="/nonexistent-erg2")
    assert report.verdict is ErgVerdict.INFRASTRUCTURE_ERROR
    assert report.verdict.value not in ("pass", "warning", "fail", "manual-review")


def test_erg2_oversize_input_fails():
    # The oversize document is generated in-test rather than stored: a 70 KB
    # static fixture of padding carries no additional signal.
    pad = "x" * 70_000
    text = (
        "apiVersion: agent-os.external-repository-governance/v1alpha1\n"
        "kind: ExternalRepositoryProfile\n"
        "governanceDocuments:\n"
        "  docs: docs/a.md\n"
        f"  pad: {pad}\n"
    )
    assert len(text.encode("utf-8")) > 65_536
    report = validate_erg_document(text, source="oversize", repo_root=REPO_ROOT)
    assert report.verdict is ErgVerdict.FAIL
    assert any(
        c.name == "strict-yaml-input-bounds" and c.verdict is ErgVerdict.FAIL
        for c in report.checks
    )


def test_erg2_alias_collision_detected_regardless_of_record_order():
    # Regression: the alias/repository collision check used to depend on
    # record order — an alias declared before the repository it collided
    # with was silently accepted.
    text = (
        "apiVersion: agent-os.external-repository-governance-registry/v1alpha1\n"
        "kind: ExternalRepositoryRegistry\n"
        "repositories:\n"
        "  - registryId: id-a\n"
        "    repository: partner/a\n"
        "    admission: admitted\n"
        "    lifecycle: active\n"
        "    profilePath: profiles/consumer.yml\n"
        "    contractVersion: agent-os.external-repository-governance/v1alpha1\n"
        "    routing:\n"
        "      ownerAgent: github-service-agent\n"
        "    aliases:\n"
        "      - partner/b\n"
        "  - registryId: id-b\n"
        "    repository: partner/b\n"
        "    admission: admitted\n"
        "    lifecycle: active\n"
        "    profilePath: profiles/consumer.yml\n"
        "    contractVersion: agent-os.external-repository-governance/v1alpha1\n"
        "    routing:\n"
        "      ownerAgent: github-service-agent\n"
    )
    report = validate_erg_document(text, source="alias-order", repo_root=REPO_ROOT)
    assert report.verdict is ErgVerdict.FAIL
    assert any(
        c.name == "registry-admission-policy"
        and c.verdict is ErgVerdict.FAIL
        and "partner/b" in " ".join(c.evidence)
        for c in report.checks
    )


def test_erg2_path_containment_oserror_is_infrastructure_error(
    tmp_path, monkeypatch
):
    # Regression: an OS-level failure while evaluating symlink containment
    # used to surface as a policy fail. Infrastructure failures must remain
    # infrastructure-error and never convert to a policy outcome.
    def _boom(path):
        raise OSError("simulated I/O failure")

    monkeypatch.setattr(os.path, "realpath", _boom)
    text = (
        "apiVersion: agent-os.external-repository-governance/v1alpha1\n"
        "kind: ExternalRepositoryProfile\n"
        "governanceDocuments:\n"
        "  docs: docs/a.md\n"
    )
    report = validate_erg_document(
        text,
        source="containment-oserror",
        repo_root=tmp_path,
        schema_dir=str(REPO_ROOT),
    )
    assert report.verdict is ErgVerdict.INFRASTRUCTURE_ERROR
    assert report.checks[0].name == "declared-path-safety"
    assert report.verdict.value not in ("pass", "warning", "fail", "manual-review")
