import json
from pathlib import Path

from reusable_capability_registry import RegistryReader, discover_capabilities
from reusable_capability_registry.serialization import discovery_result_to_payload, serialize_discovery_results

FIXTURES = Path(__file__).parent / "fixtures"


def test_payload_is_detached_from_reader_state():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    result = discover_capabilities(reader, capability_id="alpha-reader")[0]
    payload = discovery_result_to_payload(result)
    payload["capability"]["keywords"].append("corruption")  # type: ignore[index,union-attr]
    payload["discovery"]["warnings"].clear()  # type: ignore[index,union-attr]
    fresh = discovery_result_to_payload(discover_capabilities(reader, capability_id="alpha-reader")[0])
    assert "corruption" not in fresh["capability"]["keywords"]  # type: ignore[index,operator]
    assert fresh["discovery"]["warnings"]  # type: ignore[index]


def test_json_is_deterministic_and_round_trip_mutation_is_isolated():
    reader = RegistryReader(FIXTURES / "valid_registry.yml")
    results = discover_capabilities(reader, capability_id="alpha-reader")
    first = serialize_discovery_results(results)
    parsed = json.loads(first)
    parsed["results"][0]["capability"]["name"] = "changed"
    second = serialize_discovery_results(results)
    assert first == second
    assert first.endswith("\n")
    assert "informational_notice" in json.loads(first)


def test_exact_json_snapshot():
    result = discover_capabilities(
        RegistryReader(FIXTURES / "valid_registry.yml"), capability_id="alpha-reader"
    )
    actual = serialize_discovery_results(result)
    expected = '{"informational_notice":"Discovery evidence is informational and does not authorize implementation, repository writes, readiness changes, or merge.","results":[{"capability":{"canonical_paths":["src/alpha.py"],"capability_id":"alpha-reader","compatibility":[],"deprecated_by":null,"documentation_handoff":[],"extension_points":[],"failure_modes":[],"inputs":[],"invariants":["Output is deterministic."],"keywords":["Alpha","shared"],"known_consumer_exemption":null,"known_consumers":["scripts/use_alpha.py"],"name":"Alpha Reader","outputs":[],"owner_agent":"Integration Manager","public_interfaces":["alpha:Read"],"reuse_guidance":"Reuse for alpha reads only.","side_effects":["Performs no writes."],"status":"active","summary":"Reads alpha records.","supporting_agents":[],"tests":["tests/test_alpha.py"]},"discovery":{"confidence":"verified","evidence_basis":["exact-capability-id-match"],"manual_review_reasons":[],"warnings":["behavioral-compatibility-not-evaluated","consumer-evidence-not-validated","direct-module-stability-commitment","ownership-not-validated","test-evidence-not-validated"]},"informational_notice":"Discovery evidence is informational and does not authorize implementation, repository writes, readiness changes, or merge."}]}\n'
    assert actual == expected


# --- RC4 validation serializer (#494) --------------------------------------

from reusable_capability_registry.models import (  # noqa: E402
    VALIDATION_INFORMATIONAL_NOTICE,
    EvidenceConfidence,
    RegistryProvenance,
    ValidationEvidence,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
)
from reusable_capability_registry.serialization import (  # noqa: E402
    serialize_validation_report,
    validation_report_to_payload,
)


def _fail_report():
    finding = ValidationFinding(
        "structure.malformed-registry", EvidenceConfidence.CONTRADICTED, ValidationSeverity.FAIL,
        None, "structure", "registry is malformed or invalid",
        (ValidationEvidence(None, None, None, "registry", "bad"),), None,
    )
    return ValidationReport.from_findings([finding], provenance=None, capabilities_checked=1, checks_run=1)


def test_validation_report_golden_literal():
    # Golden literal: a null-provenance fail report is fully deterministic.
    actual = serialize_validation_report(_fail_report())
    expected = (
        '{"findings":[{"capability_id":null,"code":"structure.malformed-registry","confidence":"contradicted",'
        '"evidence":[{"detail":"bad","line":null,"path":null,"source_type":"registry","symbol":null}],'
        '"manual_review_reason":null,"message":"registry is malformed or invalid","severity":"fail",'
        '"surface":"structure"}],"informational_notice":' + f'"{VALIDATION_INFORMATIONAL_NOTICE}"' +
        ',"provenance":null,"report_version":"1.0","summary":{"capabilities_checked":1,"checks_run":1,'
        '"confidence_counts":{"contradicted":1,"manual-review":0,"probable":0,"unverified":0,"verified":0},'
        '"severity":"fail","severity_counts":{"fail":1,"manual-review":0,"pass":0,"warn":0}}}\n'
    )
    assert actual == expected


def test_validation_serializer_is_deterministic_and_carries_provenance():
    provenance = RegistryProvenance("registry-canonical-records", 1, "0.1.0", "a" * 64)
    report = ValidationReport.from_findings([], provenance=provenance, capabilities_checked=3, checks_run=9)
    first = serialize_validation_report(report)
    assert first == serialize_validation_report(report)
    assert first.endswith("}\n") and first.count("\n") == 1
    payload = validation_report_to_payload(report)
    assert payload["provenance"] == {
        "algorithm": "registry-canonical-records", "algorithm_version": 1, "digest": "a" * 64, "registry_version": "0.1.0",
    }
    assert payload["report_version"] == "1.0"
    assert payload["summary"]["severity"] == "pass"
