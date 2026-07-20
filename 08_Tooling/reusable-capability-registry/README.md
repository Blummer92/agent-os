# Reusable Capability Registry

Offline, read-only discovery for the Agent OS reusable-capability registry.

## Guarantees

- Reads `04_Registry/reusable-capabilities.yml` without modifying it.
- Uses immutable records and detached serialized output.
- Produces deterministic lookup results.
- Treats confidence as match strength, not behavioral validation.
- Performs no network calls, source inspection, imports, or repository writes.

## Install for development

```bash
python -m pip install -e '.[test]'
```

## CLI

```bash
agent-os-capabilities --id issue-acceptance-report
agent-os-capabilities --keyword report --format json
python -m reusable_capability_registry --owner "Integration Manager"
```

Use `--registry PATH` to read an approved fixture or alternate local registry.

Exit codes:

- `0`: one or more deterministic results
- `1`: no results
- `2`: invalid input, malformed registry, unsupported version, or ambiguous keyword-only result

All output is informational. A discovery result does not authorize implementation,
repository writes, readiness changes, or merge.

## Python API

```python
from reusable_capability_registry import RegistryReader, discover_capabilities

reader = RegistryReader()
results = discover_capabilities(reader, capability_id="issue-acceptance-report")
```

`CapabilityRecord` and `DiscoveryResult` are frozen, slotted dataclasses. Repeated
values use tuples. JSON payloads are fresh projections and share no mutable state
with the reader.

## Validation

```bash
pytest
```
