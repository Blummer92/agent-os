# Reusable Capability Registry

Offline, read-only discovery and validation for the Agent OS reusable-capability
registry.

## Guarantees

- Reads `04_Registry/reusable-capabilities.yml` without modifying it.
- Uses immutable records and detached serialized output.
- Produces deterministic discovery and validation results.
- Treats confidence and validation findings as evidence, not authorization.
- Performs no network calls, arbitrary runtime imports, or repository writes.

## Install for development

```bash
python -m pip install -e '.[test]'
```

## Discovery CLI

```bash
agent-os-capabilities --id issue-acceptance-report
agent-os-capabilities --keyword report --format json
python -m reusable_capability_registry --owner "Integration Manager"
```

Use `--registry PATH` to read an approved fixture or alternate local registry.

Exit codes:

- `0`: one or more deterministic results
- `1`: no results
- `2`: invalid input, malformed registry, unsupported version, or ambiguous result

All output is informational. A discovery result does not authorize implementation,
repository writes, readiness changes, or merge.

## Discovery API

```python
from reusable_capability_registry import RegistryReader, discover_capabilities

reader = RegistryReader()
results = discover_capabilities(reader, capability_id="issue-acceptance-report")
```

`CapabilityRecord` and `DiscoveryResult` are frozen, slotted dataclasses. Repeated
values use tuples. JSON payloads are fresh projections and share no mutable state
with the reader.

## Report-only validation API

```python
from reusable_capability_registry import (
    serialize_validation_report,
    validate_registry,
)

report = validate_registry()
print(serialize_validation_report(report), end="")
```

Validation reuses `RegistryReader`, then performs bounded static inspection for:

- canonical paths and public Python symbols;
- compatibility-preserving package re-exports;
- known-consumer and listed-test evidence;
- test-only consumer classification;
- recognized owner and supporting-agent names;
- active consumer exemptions and newly detected non-test consumers.

Results are `pass`, `warn`, `manual-review`, or `fail`. Findings use a finite reason
vocabulary and preserve human detail separately. Reports always set
`authoritative`, `mutation_authorized`, and `side_effects_performed` to `false`.
The validator does not import registered modules, mutate registry data, remove
exemptions, reassign owners, update issues, or create workflows.

## Validation

```bash
pytest
```
