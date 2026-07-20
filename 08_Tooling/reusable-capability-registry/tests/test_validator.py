from __future__ import annotations

from pathlib import Path

import yaml

from reusable_capability_registry import (
    serialize_validation_report,
    validate_registry,
    validation_report_to_payload,
)


def write_file(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_repository(
    tmp_path: Path,
    *,
    owner: str = "Integration Manager",
    interface: str = "demo:Demo",
    consumers: list[str] | None = None,
    exemption: str | None = None,
    consumer_text: str = "from demo import Demo\n",
    test_text: str = "from demo import Demo\n\ndef test_demo():\n    assert Demo\n",
) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    write_file(
        root,
        "04_Registry/agent-inheritance-registry.md",
        "| Agent | Inherits | Overlay |\n|---|---|---|\n"
        "| Integration Manager | Global Engineering | integration-manager |\n"
        "| QA / Test Agent | Global Engineering | qa-test-agent |\n",
    )
    write_file(root, "src/demo/api.py", "class Demo:\n    pass\n")
    write_file(root, "src/demo/__init__.py", "from .api import Demo\n\n__all__ = [\"Demo\"]\n")
    write_file(root, "app/consumer.py", consumer_text)
    write_file(root, "tests/test_demo.py", test_text)

    record = {
        "capability_id": "demo-capability",
        "name": "Demo Capability",
        "summary": "Fixture capability.",
        "status": "active",
        "canonical_paths": ["src/demo/api.py", "src/demo/__init__.py"],
        "public_interfaces": [interface],
        "owner_agent": owner,
        "known_consumers": ["app/consumer.py"] if consumers is None else consumers,
        "tests": ["tests/test_demo.py"],
        "keywords": ["demo"],
        "reuse_guidance": "Reuse Demo.",
        "side_effects": ["None."],
    }
    if exemption is not None:
        record["known_consumer_exemption"] = exemption
    registry = root / "04_Registry/reusable-capabilities.yml"
    registry.write_text(
        yaml.safe_dump({"registry_version": "0.1.0", "capabilities": [record]}, sort_keys=False),
        encoding="utf-8",
    )
    return root, registry


def reason_codes(report) -> set[str]:
    return {finding.reason_code for finding in report.findings}


def test_valid_registry_passes_and_output_is_deterministic(tmp_path: Path):
    root, registry = build_repository(tmp_path)
    before = registry.read_bytes()

    first = validate_registry(registry, repository_root_path=root)
    second = validate_registry(registry, repository_root_path=root)

    assert first.result == "pass"
    assert first.findings == ()
    assert first == second
    assert serialize_validation_report(first) == serialize_validation_report(second)
    assert serialize_validation_report(first).endswith("\n")
    assert registry.read_bytes() == before
    payload = validation_report_to_payload(first)
    assert payload["authoritative"] is False
    assert payload["mutation_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_malformed_registry_fails_safely(tmp_path: Path):
    root, registry = build_repository(tmp_path)
    registry.write_text("registry_version: [\n", encoding="utf-8")

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "fail"
    assert reason_codes(report) == {"registry.invalid"}


def test_missing_canonical_path_and_consumer_are_failures(tmp_path: Path):
    root, registry = build_repository(tmp_path, consumers=["app/missing.py"])
    data = yaml.safe_load(registry.read_text(encoding="utf-8"))
    data["capabilities"][0]["canonical_paths"].append("src/demo/missing.py")
    registry.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "fail"
    assert "path.missing" in reason_codes(report)
    assert "consumer.path-missing" in reason_codes(report)


def test_package_reexport_is_recognized_without_importing_module(tmp_path: Path):
    root, registry = build_repository(tmp_path, interface="demo:Demo")

    report = validate_registry(registry, repository_root_path=root)

    assert "interface.symbol-missing" not in reason_codes(report)
    assert report.result == "pass"


def test_missing_symbol_fails_and_unrelated_test_requires_review(tmp_path: Path):
    root, registry = build_repository(
        tmp_path,
        interface="demo:MissingSymbol",
        test_text="def test_unrelated():\n    assert True\n",
    )

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "fail"
    assert "interface.symbol-missing" in reason_codes(report)
    assert "test.reference-missing" in reason_codes(report)


def test_test_only_consumer_and_unrecognized_owner_fail_closed(tmp_path: Path):
    root, registry = build_repository(
        tmp_path,
        owner="Unknown Agent",
        consumers=["tests/test_demo.py"],
    )

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "fail"
    assert "consumer.test-only" in reason_codes(report)
    assert "owner.unrecognized" in reason_codes(report)
    assert report.manual_review_items


def test_active_exemption_reports_real_non_test_consumer(tmp_path: Path):
    root, registry = build_repository(
        tmp_path,
        consumers=[],
        exemption="Temporary approved exemption.",
    )
    write_file(root, "service/use_demo.py", "from demo import Demo\n")

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "warn"
    assert "exemption.real-consumer-detected" in reason_codes(report)
    assert any("service/use_demo.py" in item for item in report.exemption_findings)


def test_active_exemption_without_consumer_remains_visible(tmp_path: Path):
    root, registry = build_repository(
        tmp_path,
        consumers=[],
        exemption="Temporary approved exemption.",
    )
    (root / "app/consumer.py").unlink()

    report = validate_registry(registry, repository_root_path=root)

    assert report.result == "warn"
    assert "exemption.active" in reason_codes(report)
