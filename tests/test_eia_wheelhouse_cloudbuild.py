from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "cloudbuild.eia-wheelhouse.yaml"
ORDINARY = ROOT / "cloudbuild.yaml"


def _content() -> str:
    return CONFIG.read_text(encoding="utf-8")


def test_entrypoint_is_separate_from_ordinary_validation_config():
    ordinary = ORDINARY.read_text(encoding="utf-8")
    assert "./scripts/validate-all.sh" in ordinary
    assert "dependency_artifact_qualification" not in ordinary
    assert "eia-paddleocr-cp311-wheelhouse-qualification" not in ordinary


def test_entrypoint_is_fixed_to_canonical_qualification_module_and_profile():
    content = _content()
    assert "python -m workflow_scheduler.governance.dependency_artifact_qualification" in content
    assert "eia-paddleocr-cp311-wheelhouse-qualification" in content
    assert "paddleocr==3.7.0" in content
    assert "paddlepaddle==3.2.0" in content
    assert "paddlex==3.7.2" in content
    assert "manylinux2014_x86_64" in content
    assert "cp311" in content


def test_entrypoint_accepts_only_expected_sha_substitution():
    content = _content()
    assert "_EXPECTED_SHA" in content
    assert "_PACKAGE" not in content
    assert "_INDEX" not in content
    assert "_PLATFORM" not in content
    assert "_ABI" not in content
    assert "_PYTHON" not in content
    assert "_COMMAND" not in content
    assert "_ARGS" not in content
    assert "_DEST" not in content
    assert "_URL" not in content


def test_entrypoint_verifies_repository_and_exact_checkout_sha():
    content = _content()
    assert 'tested_sha="$(git rev-parse HEAD)"' in content
    assert 'test "${tested_sha}" = "${_EXPECTED_SHA}"' in content
    assert 'test "$(git remote get-url origin)" = "https://github.com/Blummer92/agent-os.git"' in content
    assert 'test "$(git rev-parse HEAD)" = "${_EXPECTED_SHA}"' in content


def test_entrypoint_does_not_mutate_gce_or_cloud_authority_surfaces():
    content = _content()
    forbidden = (
        "gcloud compute",
        "gcloud iam",
        "secret",
        "service-account",
        "agent-os-test",
        "sudo",
        "ssh",
        "gsutil",
        "curl ",
        "wget ",
        "pip install",
    )
    for token in forbidden:
        assert token not in content


def test_entrypoint_bounds_and_validates_non_authorizing_evidence():
    content = _content()
    assert "32768" in content
    assert "cleanup_complete" in content
    for key in (
        "execution_authorized",
        "host_mutation_authorized",
        "scheduler_invoked",
        "production_authorized",
        "classroom_data_authorized",
    ):
        assert key in content
        assert f"payload.get(key) is not False" in content


def test_entrypoint_preserves_cloud_logging_only():
    assert "logging: CLOUD_LOGGING_ONLY" in _content()
