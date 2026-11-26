"""Shared invariants for records consumed as already validated evidence."""
from dataclasses import replace

import pytest

from instructional_workflow_contracts.common import (
    MAX_INPUT_BYTES,
    ContractValidationError,
    FrozenArray,
    FrozenObject,
    ValidatedRecord,
    ValidationResult,
    ValidationStatus,
    canonical_json_bytes,
    freeze_json,
    sanitize_detail,
    sha256_hex,
    validate_and_normalize_json,
    validate_exact_fields,
    validate_reason_code,
)


def _record() -> ValidatedRecord:
    payload = freeze_json({"b": [1, True, None], "a": "lesson"})
    return ValidatedRecord("contract-v1", "lesson-1", 1, "sha256", sha256_hex(payload), payload)


def test_record_rejects_a_well_formed_but_unbound_fingerprint():
    record = _record()
    assert record.fingerprint == sha256_hex(record.to_dict())
    with pytest.raises(ContractValidationError, match="does not match"):
        replace(record, fingerprint="0" * 64)


@pytest.mark.parametrize(("status", "reasons", "blockers"), [
    (ValidationStatus.BLOCKED, ("handoff-invalid",), ("routing-blocked-dependency",)),
    (ValidationStatus.STALE, ("source-conflicting",), ()),
    (ValidationStatus.STALE, (), ()),
    (ValidationStatus.MANUAL_REVIEW_REQUIRED, ("source-stale",), ()),
])
def test_shared_reason_cannot_disagree_with_the_record_status(status, reasons, blockers):
    with pytest.raises(ValueError):
        ValidationResult(status, _record(), reasons, blockers)


@pytest.mark.parametrize("key", [
    "passwords", "credentials", "api_keys", "secrets", "token", "Bearer", "session",
])
def test_token_and_plural_secret_keys_are_refused(key):
    with pytest.raises(ContractValidationError) as caught:
        validate_and_normalize_json({"row": {key: "synthetic"}})
    assert caught.value.reason_code == "authority-secret-field"


def test_bounded_diagnostics_hide_labelled_values():
    for text in (
        'password="synthetic value with spaces"',
        'api_keys: synthetic',
        'Authorization: Bearer synthetic',
        'prefixed_credentials=synthetic',
        'a' * 485 + ' token=synthetic' * 60,
    ):
        detail = sanitize_detail(text)
        assert "synthetic" not in detail
        assert "[redacted]" in detail or len(detail) <= 500


def test_bad_reason_code_uses_one_bounded_validation_error():
    with pytest.raises(ContractValidationError) as caught:
        validate_reason_code("wrong:syntax")
    assert caught.value.reason_code == "handoff-invalid"
    error = ContractValidationError("wrong:syntax", "raw")
    assert error.reason_code == "handoff-invalid"
    assert "raw" not in error.detail


def test_explicit_large_limit_does_not_bypass_global_byte_limit():
    with pytest.raises(ContractValidationError, match="serialized-size"):
        validate_and_normalize_json(["a" * 512] * 130, max_bytes=MAX_INPUT_BYTES * 4)


def test_exact_fields_wrong_type_is_classified_without_hashing_items():
    with pytest.raises(ContractValidationError) as caught:
        validate_exact_fields([[]], frozenset({"source"}), "root")
    assert caught.value.reason_code == "handoff-wrong-type"


@pytest.mark.parametrize("build", [
    lambda: FrozenArray(({"mutable": True},)),
    lambda: FrozenObject((("key", []),)),
    lambda: FrozenObject((("key", 1), ("key", 2))),
])
def test_direct_frozen_construction_cannot_hide_mutable_or_duplicate_values(build):
    with pytest.raises((ContractValidationError, TypeError)):
        build()


def test_hash_validates_direct_frozen_input_too():
    with pytest.raises(ContractValidationError) as caught:
        canonical_json_bytes(FrozenObject((("token", "synthetic"),)))
    assert caught.value.reason_code == "authority-secret-field"


def test_freezing_and_thawing_refuse_overdeep_inputs():
    raw, frozen = None, None
    for _ in range(20):
        raw = [raw]
        frozen = FrozenArray((frozen,))
    with pytest.raises(ContractValidationError, match="nesting-depth"):
        freeze_json(raw)
    with pytest.raises(ContractValidationError, match="nesting-depth"):
        canonical_json_bytes(frozen)


@pytest.mark.parametrize("text", [
    r'password="prefix\"synthetic-suffix"',
    r"token='prefix\'synthetic-suffix'",
])
def test_escaped_quote_does_not_end_redaction_early(text):
    assert "synthetic-suffix" not in sanitize_detail(text)


@pytest.mark.parametrize("value", [
    '"synthetic-first synthetic-last"',
    r'"synthetic-first\"synthetic-last"',
    r'\"synthetic-first synthetic-last\"',
    r'\\"synthetic-first synthetic-last\\"',
    r"""'"synthetic-first" 'inside' synthetic-last'""",
    r'''"synthetic-first "nested" synthetic-last"''',
    r'''{"item": "synthetic-first", "detail": "synthetic-last"}''',
], ids=["plain", "escaped-quote", "escaped-wrapper", "double-escaped-wrapper", "nested-single", "nested-double", "nested-object"])
def test_aos_4123_04_credential_diagnostic_consumes_entire_value(value):
    cleaned = sanitize_detail(f"diagnostic password={value}")
    assert cleaned.startswith("diagnostic [redacted]")
    assert "synthetic-first" not in cleaned and "synthetic-last" not in cleaned


@pytest.mark.parametrize("layers", [1, 2, 3])
def test_aos_4123_04_serialized_credential_diagnostic(layers):
    import json

    raw = {"api_key": 'synthetic-first "inside" synthetic-last'}
    for _ in range(layers):
        raw = json.dumps(raw)
    cleaned = sanitize_detail(f"diagnostic {raw}")
    assert "[redacted]" in cleaned
    assert "synthetic-first" not in cleaned and "synthetic-last" not in cleaned
