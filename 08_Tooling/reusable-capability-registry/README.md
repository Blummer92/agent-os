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

## Snapshot provenance

```python
from reusable_capability_registry.provenance import provenance_for_registry

provenance = provenance_for_registry()  # RegistryProvenance
```

Provenance is a deterministic, offline SHA-256 digest (`algorithm
registry-canonical-records`, version `1`) computed from the validated parsed
records plus `registry_version` — never from raw YAML bytes. Records are ordered
by `capability_id` and governed set-like lists by exact Unicode code point;
duplicate set-like values fail closed. Formatting-only edits keep the digest;
any semantic change (including case, path spelling, or Unicode composed/decomposed
form) changes it. `discover_capabilities(reader, ..., attach_provenance=True)`
attaches equal provenance to every result; the default omits it and preserves the
legacy output byte-for-byte.

Matching provenance proves only that two artifacts were computed from the same
canonical registry snapshot. It does **not** prove correctness, freshness,
authorship, trustworthiness, authorization, compatibility, test adequacy,
ownership validity, approval, readiness, or permission to execute or write.

## Supported PyYAML versions

The package supports `PyYAML>=6.0,<7`. The duplicate-key loader contract is
proven across that range by a bounded compatibility matrix
(`.github/workflows/reusable-capability-registry-pyyaml-compat.yml`) covering the
minimum (`6.0`), the ordinary-CI-resolved, and the newest compatible `<7`
release. The declared range is changed only with evidence from a failing matrix
lane and a separate explicit decision.

## Validation

```bash
pytest
```
