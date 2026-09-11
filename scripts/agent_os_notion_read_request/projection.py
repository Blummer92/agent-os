"""Sanitized public projection for one bounded #2283 Notion read result.

The sensitive-data boundary is structural, not a natural-language phrase list:

1. The only inputs are the repository-owned catalog and the #973 validated state
   record. A raw Notion response is never an input, so raw page bodies, private
   property values, and workspace dumps cannot reach the public surface.
2. Every projected object is rebuilt field-by-field from a fixed key allowlist,
   so a new upstream field is dropped by default rather than published.
3. Evidence references keep provenance (``system``/``stable_id``) but drop
   ``exact_location`` and ``verification_evidence``, which can disclose private
   page locations.
4. A final structural guard walks the finished payload and refuses any
   credential-class key that carries anything but a boolean state flag, so a
   token, header, or secret-derived diagnostic cannot be written.
"""

from __future__ import annotations

from typing import Any, Mapping

from navigation_registry.connectors.curriculum_evidence_orchestrator import MAX_RESULTS

from .models import (
    CREDENTIAL_KEY_FRAGMENTS,
    SCHEMA_VERSION,
    NotionReadAdmission,
    NotionReadCatalog,
    NotionReadRequestError,
)

RESULT_KIND = "agent-os-notion-read-result"

_OWNER_STATE_KEYS = (
    "evidence_id",
    "owner",
    "decision_key",
    "value",
    "source_revision",
    "observed_at",
)
_CONTEXT_EVIDENCE_KEYS = _OWNER_STATE_KEYS + ("classification", "currentness", "material")
_STALE_EVIDENCE_KEYS = (
    "evidence_id",
    "owner",
    "decision_key",
    "source_revision",
    "observed_at",
)
_CONTRADICTION_KEYS = ("kind", "decision_key", "evidence_ids", "owners")
_ASSET_SUMMARY_KEYS = (
    "matching_asset_exists",
    "approved_for_requested_use_exists",
    "approved_reusable_student_facing_exists",
    "production_authorized",
    "asset_ids",
    "eligible_asset_ids",
)
#: Provenance is kept; private location disclosure is not.
_REFERENCE_KEYS = ("system", "stable_id")


def project_public_result(
    admission: NotionReadAdmission,
    execution: Mapping[str, object],
    *,
    catalog: NotionReadCatalog,
    generated_at: str,
) -> dict[str, Any]:
    """Return the bounded sanitized result for the public GitHub surface."""
    if admission.status != "admitted":
        raise NotionReadRequestError("only an admitted request may be projected")
    if not isinstance(execution, Mapping):
        raise NotionReadRequestError("execution evidence must be a mapping")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise NotionReadRequestError("generated_at must be supplied by the caller")

    state = execution.get("state_payload")
    if not isinstance(state, Mapping):
        raise NotionReadRequestError("execution evidence is missing #973 state")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "result_kind": RESULT_KIND,
        "repository": admission.repository,
        "issue_number": admission.issue_number,
        "request_id": admission.request_id,
        "request_class": admission.request_class,
        "read_route": execution.get("read_route"),
        "state_status": execution.get("state_status"),
        "canonical_unit": _canonical_unit(state, admission),
        "sources": _sources(admission, catalog),
        "currentness": {
            "state_id": state.get("state_id"),
            "contract_version": state.get("contract_version"),
            "disposition": state.get("disposition"),
            "resolved_day_id": state.get("resolved_day_id"),
            "unresolved_teacher_decision": state.get("unresolved_teacher_decision"),
            "next_legitimate_owner": state.get("next_legitimate_owner"),
            "reason_codes": _string_list(state.get("reason_codes")),
            "blockers": _string_list(state.get("blockers")),
            "stale_evidence": _records(state.get("stale_evidence"), _STALE_EVIDENCE_KEYS),
            "contradictions": _records(state.get("contradictions"), _CONTRADICTION_KEYS),
        },
        "owner_evidence": _records(state.get("owner_states"), _OWNER_STATE_KEYS),
        "context_evidence": _records(state.get("context_evidence"), _CONTEXT_EVIDENCE_KEYS),
        "assets": _assets(state.get("assets")),
        "provenance": {
            "curriculum_source_of_truth": "notion-working-curriculum",
            "governance_source_of_truth": "github-agent-os",
            "evidence_class": "request-scoped-projection",
            "authoritative_curriculum_record": False,
            "durable_curriculum_store": False,
        },
        "authority": _authority(state.get("authority")),
        "generated_at": generated_at.strip(),
    }

    reject_credential_keys(payload)
    return payload


def _canonical_unit(state: Mapping[str, object], admission: NotionReadAdmission) -> dict[str, Any]:
    unit = state.get("canonical_unit")
    if not isinstance(unit, Mapping):
        raise NotionReadRequestError("#973 state is missing canonical unit identity")
    return {
        "canonical_unit_key": admission.canonical_unit_key,
        "stable_id": unit.get("stable_id"),
        "status": unit.get("status"),
    }


def _sources(admission: NotionReadAdmission, catalog: NotionReadCatalog) -> list[dict[str, Any]]:
    """Project provider-neutral source identity only.

    The provider data-source id stays inside the execution seam: #975 evidence is
    provider-neutral, and the public surface needs no Notion-specific target.
    """
    projected: list[dict[str, Any]] = []
    for logical_source in admission.required_logical_sources:
        binding = catalog.source(logical_source)
        if binding is None:
            raise NotionReadRequestError(
                f"admitted source vanished from the catalog: {logical_source!r}"
            )
        projected.append(
            {
                "logical_source": binding.logical_source,
                "display_name": binding.display_name,
                "content_class": binding.content_class,
                "verification_state": binding.verification_state,
                "access": "read-only",
            }
        )
    return projected


def _assets(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NotionReadRequestError("#973 state is missing the asset summary")
    summary = {key: value.get(key) for key in _ASSET_SUMMARY_KEYS}
    for key in ("asset_ids", "eligible_asset_ids"):
        summary[key] = _string_list(summary.get(key))
    # Inherit #973's asset authority rather than overwriting it. Overwriting
    # would publish a fail-closed value even if the canonical summary ever
    # reported something else, masking upstream truth instead of surfacing it.
    if summary["production_authorized"] is not False:
        raise NotionReadRequestError(
            "#973 asset summary production_authorized is not fail-closed"
        )
    # Restate the #971/#973 boundary explicitly so a public reader cannot infer
    # approval or production authority from mere existence.
    summary["existence_implies_approved_use"] = False
    summary["existence_implies_production_authority"] = False
    summary["relation_source"] = "canonical-unit-relation"
    summary["title_or_filename_matching_used"] = False
    return summary


def _authority(value: object) -> dict[str, Any]:
    declared = value if isinstance(value, Mapping) else {}
    authority = {
        "execution_authorized": False,
        "external_write_authorized": False,
        "notion_write_authorized": False,
        "drive_write_authorized": False,
        "classroom_artifact_write_authorized": False,
        "production_authorized": False,
        "publication_authorized": False,
        "write_allowed": False,
    }
    for key, declared_value in declared.items():
        # An upstream record may never widen authority through projection.
        if declared_value is not False:
            raise NotionReadRequestError(f"#973 authority field is not fail-closed: {key!r}")
    return authority


def _records(value: object, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise NotionReadRequestError("bounded evidence collection must be a list")
    if len(value) > MAX_RESULTS:
        raise NotionReadRequestError("bounded evidence collection exceeds the read limit")
    projected: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise NotionReadRequestError("bounded evidence record must be a mapping")
        record: dict[str, Any] = {}
        for key in keys:
            if key in item:
                record[key] = _scalar_or_list(item[key])
        if "reference" in item:
            record["reference"] = _reference(item["reference"])
        projected.append(record)
    return projected


def _reference(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NotionReadRequestError("evidence reference must be a mapping")
    return {key: _text_or_none(value.get(key)) for key in _REFERENCE_KEYS}


def _scalar_or_list(value: object) -> Any:
    if isinstance(value, (list, tuple)):
        return [_scalar_or_list(item) for item in value]
    if isinstance(value, Mapping):
        raise NotionReadRequestError("unexpected nested object in bounded evidence")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise NotionReadRequestError("unsupported value type in bounded evidence")


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise NotionReadRequestError("bounded string list must be a list")
    if len(value) > MAX_RESULTS:
        raise NotionReadRequestError("bounded string list exceeds the read limit")
    return [str(item) for item in value]


def _text_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def reject_credential_keys(value: object, path: str = "result") -> None:
    """Fail closed if a credential-class key carries anything but a boolean.

    A credential-class key may only ever hold a boolean state flag (for example
    ``secret_dispatch_authorized``), because a boolean cannot carry a token,
    header, or secret-derived diagnostic. Any other value under such a key -- a
    string, number, list, or nested object -- is refused. This is a general
    structural rule, so it needs no per-name exemption list to maintain.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in CREDENTIAL_KEY_FRAGMENTS):
                if type(item) is not bool:
                    raise NotionReadRequestError(
                        f"credential-class key is not publishable: {path}.{key}"
                    )
                continue
            reject_credential_keys(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            reject_credential_keys(item, f"{path}[{index}]")


__all__ = ["RESULT_KIND", "project_public_result", "reject_credential_keys"]
