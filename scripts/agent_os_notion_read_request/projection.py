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
#: #2816: the source-schema class publishes property vocabulary, not records.
RESULT_KIND_SCHEMA = "agent-os-notion-source-schema-result"
#: #3580: the lesson-content class publishes bounded lesson field records.
RESULT_KIND_LESSON_CONTENT = "agent-os-notion-lesson-content-result"

#: #2816: verified Visual Asset Library "Reuse status" select property id.
#: Recovered from governed source-schema runs 38322797691/38322852601.
#: Select-option metadata is emitted only for this exact property id; every
#: other property keeps the triple-only projection.
REUSE_STATUS_PROPERTY_ID = "MR%3Do"

#: Bound on select options emitted for the bound property. A larger option
#: list is treated as malformed and fails closed.
MAX_SELECT_OPTIONS = 50

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


def project_source_schema_result(
    admission: NotionReadAdmission,
    execution: Mapping[str, object],
    *,
    catalog: NotionReadCatalog,
    generated_at: str,
) -> dict[str, Any]:
    """Return the bounded sanitized source-schema result for the public surface.

    Only property id/name/type triples are published. Every other adapter
    field (url, parent, timestamps, request ids) is dropped by construction,
    and the provider data-source id stays inside the execution seam, exactly
    as it does for the record-read projection above.
    """
    if admission.status != "admitted":
        raise NotionReadRequestError("only an admitted request may be projected")
    if admission.request_class != "source-schema":
        raise NotionReadRequestError(
            "source-schema projection requires the source-schema request class"
        )
    if not isinstance(execution, Mapping):
        raise NotionReadRequestError("execution evidence must be a mapping")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise NotionReadRequestError("generated_at must be supplied by the caller")
    if len(admission.required_logical_sources) != 1:
        raise NotionReadRequestError(
            "source-schema admission must bind exactly one logical source"
        )
    binding = catalog.source(admission.required_logical_sources[0])
    if binding is None:
        raise NotionReadRequestError("admitted source vanished from the catalog")

    properties = execution.get("properties")
    if not isinstance(properties, Mapping):
        raise NotionReadRequestError("execution evidence is missing source properties")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "result_kind": RESULT_KIND_SCHEMA,
        "repository": admission.repository,
        "issue_number": admission.issue_number,
        "request_id": admission.request_id,
        "request_class": admission.request_class,
        "source": {
            "logical_source": binding.logical_source,
            "display_name": binding.display_name,
            "verification_state": binding.verification_state,
            "access": "read-only",
        },
        "properties": _property_triples(properties),
        "authority": _authority({}),
        "generated_at": generated_at.strip(),
    }

    reject_credential_keys(payload)
    return payload


#: #3580: the governed lesson-content field contract. Exactly the 7 result keys
#: below are projected per lesson; every other property on the record is
#: dropped by construction. "Key Vocabulary" is emitted as absent (None) when
#: the property is missing or empty — it is never invented.
_LESSON_RESULT_KEYS = (
    "daily_learning_target",
    "daily_focus",
    "key_vocabulary",
    "canonical_unit",
    "source_evidence",
    "day_lesson_number",
    "record_url",
)


def project_lesson_content_result(
    admission: NotionReadAdmission,
    execution: Mapping[str, object],
    *,
    catalog: NotionReadCatalog,
    generated_at: str,
) -> dict[str, Any]:
    """Return the bounded sanitized lesson-content result for the public surface.

    Only the 7 governed lesson fields are published per record. Every other
    adapter field (page ids beyond the canonical-unit relation, timestamps,
    parent references, unlisted properties) is dropped by construction, and
    the provider data-source id stays inside the execution seam, exactly as
    it does for the source-schema projection above. Empty or missing fields
    are emitted as absent (None); nothing is invented, defaulted, or inferred.
    """
    if admission.status != "admitted":
        raise NotionReadRequestError("only an admitted request may be projected")
    if admission.request_class != "lesson-content":
        raise NotionReadRequestError(
            "lesson-content projection requires the lesson-content request class"
        )
    if not isinstance(execution, Mapping):
        raise NotionReadRequestError("execution evidence must be a mapping")
    if not isinstance(generated_at, str) or not generated_at.strip():
        raise NotionReadRequestError("generated_at must be supplied by the caller")
    if len(admission.required_logical_sources) != 1:
        raise NotionReadRequestError(
            "lesson-content admission must bind exactly one logical source"
        )
    binding = catalog.source(admission.required_logical_sources[0])
    if binding is None:
        raise NotionReadRequestError("admitted source vanished from the catalog")

    records = execution.get("records")
    if not isinstance(records, list):
        raise NotionReadRequestError("execution evidence is missing lesson records")
    if len(records) > MAX_RESULTS:
        raise NotionReadRequestError("lesson record count exceeds the read limit")

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "result_kind": RESULT_KIND_LESSON_CONTENT,
        "repository": admission.repository,
        "issue_number": admission.issue_number,
        "request_id": admission.request_id,
        "request_class": admission.request_class,
        "source": {
            "logical_source": binding.logical_source,
            "display_name": binding.display_name,
            "verification_state": binding.verification_state,
            "access": "read-only",
        },
        "lessons": [_project_lesson_record(record) for record in records],
        "authority": _authority({}),
        "generated_at": generated_at.strip(),
    }

    reject_credential_keys(payload)
    return payload


def _project_lesson_record(record: object) -> dict[str, Any]:
    """Project exactly the 7 governed fields from one lesson page record."""
    if not isinstance(record, Mapping):
        raise NotionReadRequestError("lesson record must be a mapping")
    properties = record.get("properties")
    if not isinstance(properties, Mapping):
        raise NotionReadRequestError("lesson record is missing properties")
    lesson: dict[str, Any] = {
        "daily_learning_target": _lesson_text(properties, "Daily Learning Target"),
        "daily_focus": _lesson_text(properties, "Daily Focus"),
        # #3580: Key Vocabulary is empty on all sampled lessons. Absent is
        # emitted as None; a value is never synthesized.
        "key_vocabulary": _lesson_text(properties, "Key Vocabulary"),
        "canonical_unit": {
            "page_id": _lesson_relation_page_id(properties, "Canonical Unit"),
        },
        "source_evidence": _lesson_text(properties, "Source Evidence"),
        "day_lesson_number": _lesson_text(properties, "Day / Lesson Number"),
        "record_url": _text_or_none(record.get("url")),
    }
    if set(lesson.keys()) != set(_LESSON_RESULT_KEYS):
        raise NotionReadRequestError("lesson projection key contract drift")
    return lesson


def _lesson_text(properties: Mapping[str, object], name: str) -> str | None:
    """Extract plain text for one governed field, or None when absent/empty.

    Handles the text-shaped Notion property types (title, rich_text, select,
    status, multi_select). An unrecognized property type fails closed rather
    than guessing a rendering.
    """
    prop = properties.get(name)
    if prop is None:
        return None
    if not isinstance(prop, Mapping):
        raise NotionReadRequestError(f"lesson property {name!r} must be a mapping")
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return _plain_text_segments(prop.get(prop_type))
    if prop_type in ("select", "status"):
        option = prop.get(prop_type)
        if option is None:
            return None
        if not isinstance(option, Mapping):
            raise NotionReadRequestError(f"lesson property {name!r} has malformed option")
        return _text_or_none(option.get("name"))
    if prop_type == "multi_select":
        options = prop.get("multi_select")
        if not isinstance(options, list):
            raise NotionReadRequestError(
                f"lesson property {name!r} has malformed options"
            )
        names = [
            _text_or_none(option.get("name"))
            for option in options
            if isinstance(option, Mapping)
        ]
        names = [n for n in names if n]
        return ", ".join(names) if names else None
    raise NotionReadRequestError(
        f"lesson property {name!r} has unrecognized type {prop_type!r}"
    )


def _plain_text_segments(segments: object) -> str | None:
    if segments is None:
        return None
    if not isinstance(segments, list):
        raise NotionReadRequestError("lesson text property has malformed segments")
    texts = [
        _text_or_none(segment.get("plain_text"))
        for segment in segments
        if isinstance(segment, Mapping)
    ]
    texts = [t for t in texts if t]
    return "".join(texts) if texts else None


def _lesson_relation_page_id(
    properties: Mapping[str, object], name: str
) -> str | None:
    """Return the single related page id, normalized to dashed UUID form.

    Zero relations emit absent (None). More than one relation fails closed:
    the governed contract names a single canonical unit and the projection
    must not pick arbitrarily.
    """
    prop = properties.get(name)
    if prop is None:
        return None
    if not isinstance(prop, Mapping):
        raise NotionReadRequestError(f"lesson property {name!r} must be a mapping")
    if prop.get("type") != "relation":
        raise NotionReadRequestError(
            f"lesson property {name!r} is not a relation"
        )
    relations = prop.get("relation")
    if not isinstance(relations, list):
        raise NotionReadRequestError(
            f"lesson property {name!r} has malformed relations"
        )
    ids = [
        _text_or_none(item.get("id"))
        for item in relations
        if isinstance(item, Mapping)
    ]
    ids = [i for i in ids if i]
    if len(ids) > 1:
        raise NotionReadRequestError(
            f"lesson property {name!r} has ambiguous relations"
        )
    if not ids:
        return None
    return _dashed_uuid(ids[0])


def _dashed_uuid(value: str) -> str:
    """Normalize a Notion id to dashed lowercase UUID form."""
    compact = value.replace("-", "").lower()
    if len(compact) != 32 or any(c not in "0123456789abcdef" for c in compact):
        raise NotionReadRequestError("lesson relation id is not a Notion id")
    return (
        f"{compact[0:8]}-{compact[8:12]}-{compact[12:16]}"
        f"-{compact[16:20]}-{compact[20:32]}"
    )


def _bound_select_options(schema: Mapping[str, object]) -> list[dict[str, str]] | None:
    """Return option id/name pairs for the verified Reuse status select.

    Returns None for every other property (triple-only, unchanged). Raises
    NotionReadRequestError when the bound property is present but malformed:
    not a select, missing select schema, non-list or oversized options, or
    an option without a stable id/name. Fails closed; nothing is guessed,
    defaulted, or inferred.
    """
    if _text_or_none(schema.get("id")) != REUSE_STATUS_PROPERTY_ID:
        return None
    if _text_or_none(schema.get("type")) != "select":
        raise NotionReadRequestError("bound Reuse status property is not a select")
    select = schema.get("select")
    if not isinstance(select, Mapping):
        raise NotionReadRequestError(
            "bound Reuse status property is missing select schema"
        )
    options = select.get("options")
    if not isinstance(options, list):
        raise NotionReadRequestError(
            "bound Reuse status property has malformed options"
        )
    if len(options) > MAX_SELECT_OPTIONS:
        raise NotionReadRequestError(
            "bound Reuse status property exceeds the option bound"
        )
    projected: list[dict[str, str]] = []
    for option in options:
        if not isinstance(option, Mapping):
            raise NotionReadRequestError("bound Reuse status option must be a mapping")
        option_id = _text_or_none(option.get("id"))
        option_name = _text_or_none(option.get("name"))
        if not option_id or not option_name:
            raise NotionReadRequestError(
                "bound Reuse status option is missing id or name"
            )
        # Only the stable identifier and the display name are published;
        # color and every other option field are dropped by construction.
        projected.append({"option_id": option_id, "option_name": option_name})
    return projected


def _property_triples(properties: Mapping[str, object]) -> list[dict[str, Any]]:
    """Project exactly id/name/type per property; drop everything else."""
    if len(properties) > MAX_RESULTS:
        raise NotionReadRequestError("source property count exceeds the read limit")
    triples: list[dict[str, Any]] = []
    for key, schema in properties.items():
        if not isinstance(schema, Mapping):
            raise NotionReadRequestError("source property schema must be a mapping")
        triple: dict[str, Any] = {
            "property_id": _text_or_none(schema.get("id")),
            "property_name": _text_or_none(schema.get("name"))
            or _text_or_none(key),
            "property_type": _text_or_none(schema.get("type")),
        }
        options = _bound_select_options(schema)
        if options is not None:
            triple["select_options"] = options
        triples.append(triple)
    return triples


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


__all__ = [
    "RESULT_KIND",
    "RESULT_KIND_SCHEMA",
    "RESULT_KIND_LESSON_CONTENT",
    "project_public_result",
    "project_source_schema_result",
    "project_lesson_content_result",
    "reject_credential_keys",
]
