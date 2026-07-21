from __future__ import annotations

import json
from collections.abc import Iterable

from .discovery import INFORMATIONAL_NOTICE
from .models import CapabilityRecord, DiscoveryResult


def _record_to_payload(record: CapabilityRecord) -> dict[str, object]:
    return {
        "capability_id": record.capability_id,
        "name": record.name,
        "summary": record.summary,
        "status": record.status,
        "canonical_paths": list(record.canonical_paths),
        "public_interfaces": list(record.public_interfaces),
        "owner_agent": record.owner_agent,
        "supporting_agents": list(record.supporting_agents),
        "known_consumers": list(record.known_consumers),
        "known_consumer_exemption": record.known_consumer_exemption,
        "tests": list(record.tests),
        "keywords": list(record.keywords),
        "reuse_guidance": record.reuse_guidance,
        "side_effects": list(record.side_effects),
        "inputs": list(record.inputs),
        "outputs": list(record.outputs),
        "extension_points": list(record.extension_points),
        "invariants": list(record.invariants),
        "failure_modes": list(record.failure_modes),
        "compatibility": list(record.compatibility),
        "documentation_handoff": list(record.documentation_handoff),
        "deprecated_by": record.deprecated_by,
    }


def discovery_result_to_payload(result: DiscoveryResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "capability": _record_to_payload(result.capability),
        "discovery": {
            "confidence": result.confidence.value,
            "evidence_basis": list(result.evidence_basis),
            "warnings": list(result.warnings),
            "manual_review_reasons": list(result.manual_review_reasons),
        },
        "informational_notice": INFORMATIONAL_NOTICE,
    }
    # Populated provenance is serialized deterministically; absent provenance is
    # omitted so approved legacy output is preserved byte-for-byte.
    if result.provenance is not None:
        payload["provenance"] = result.provenance.to_payload()
    return payload


def serialize_discovery_results(results: Iterable[DiscoveryResult]) -> str:
    payload = {
        "informational_notice": INFORMATIONAL_NOTICE,
        "results": [discovery_result_to_payload(result) for result in results],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def render_text_results(results: Iterable[DiscoveryResult]) -> str:
    result_list = list(results)
    lines = [INFORMATIONAL_NOTICE]
    for result in result_list:
        lines.extend(
            [
                "",
                f"{result.capability.capability_id} [{result.confidence.value}]",
                f"  name: {result.capability.name}",
                f"  owner: {result.capability.owner_agent}",
                f"  status: {result.capability.status}",
                f"  evidence: {', '.join(result.evidence_basis)}",
                f"  warnings: {', '.join(result.warnings)}",
            ]
        )
        if result.manual_review_reasons:
            lines.append(f"  manual_review: {', '.join(result.manual_review_reasons)}")
    return "\n".join(lines) + "\n"
