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
