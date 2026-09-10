# Canonical JSON classification

Issue: #1733

## Rule

Agent OS does not have one repository-global canonical JSON contract. Similar
`json.dumps(...)` calls may be representation-equivalent while remaining
contract-distinct because their output feeds different identity domains,
persistence formats, validators, or external protocols.

Consolidation is permitted only when byte equivalence and dependency direction
are both proven safe. A matching serializer expression alone is not enough.

## Classification matrix

| Family | Representative owners | Rendering contract | Downstream contract | Classification | Disposition |
| --- | --- | --- | --- | --- | --- |
| Issue-acceptance decision JSON | `operating_mode.py`, `executor_route.py` | sorted keys, compact separators, `ensure_ascii=False`, text then UTF-8 | domain-separated SHA-256 decision IDs | representation-equivalent-but-contract-distinct | Preserve owner-local serializers and identity prefixes; regression-test exact non-ASCII bytes and domain separation. |
| Environment-health JSON | `scripts/agent_os_environment_health.py` | sorted keys, compact separators, `ensure_ascii=True`, UTF-8 bytes | environment-health evidence identity | semantically-distinct | Preserve. Changing `ensure_ascii` changes non-ASCII bytes. |
| Remote-validation JSON | `selector.py`, `advisory_gate.py`, `baseline_health.py`, related packet serializers | owner-specific canonical bytes/text | request/result/advisory identities and validation contracts | persisted/identity-bound-must-remain | Preserve unless a future owner-specific migration proves final identity equivalence. |
| Other repository serializers | candidate packets, scheduler handoffs, capture/runtime evidence and other domain packages | package-specific | validators, hashes, persisted or transported envelopes | unclassified by this bounded change | No consolidation without an owner-local equivalence proof and golden fixtures. |

## Regression requirement

Any future consolidation must include fixtures that prove exact UTF-8 bytes for
ASCII and non-ASCII inputs. When output participates in an ID, signature,
fingerprint, cache key, persistence record, or transport envelope, tests must
also compare the final downstream identity/serialized artifact rather than only
intermediate JSON text.

## #2274 drift disposition

The non-ASCII drift signal is treated as a correctness boundary, not as evidence
for a global helper. `ensure_ascii=True` and `ensure_ascii=False` serializers are
not byte-equivalent for non-ASCII input and therefore must not be consolidated
without an explicit contract migration.

## Current reduction decision

This bounded pass intentionally makes no production serializer replacement.
The strongest proven duplicate pair (`operating_mode.py` and
`executor_route.py`) renders the same bytes but feeds deliberately different
identity domains. A shared helper would reduce only a one-line implementation
while increasing cross-owner coupling. Preserving those local helpers is the
value-positive outcome until a larger exact-equivalent owner-local group is
proven.