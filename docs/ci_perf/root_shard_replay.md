# Root suite sharding experiment

Goal: a three-minute workflow-to-verdict target, with five minutes the
maximum acceptable. Keep the current required gate in charge during the
experiment. This tool is an offline timing replay, not an Actions workflow,
a gate, or a replacement for test collection. It never chooses tests.

## Run an offline replay

Use Python 3.11+ on a POSIX host, a local checkout with the reviewed Git
commit, the original JUnit ZIP, and an independently verified reference
record. The reference record must bind the provider's artifact digest to
the source commit, run, attempt and artifact, and include the complete
independent inventory of expected JUnit row identities and their source
files. Supply both expected digests from trusted channels, not from hashing
unverified files after download.

```sh
python -m scripts.ci_perf.root_shard_replay \
  --archive junit-aggregate-1.zip --archive-sha256 "$ARTIFACT_SHA256" \
  --source-head "$SOURCE_HEAD" --reference verified-root-reference.json \
  --reference-sha256 "$TRUSTED_REFERENCE_SHA256" \
  --run-id "$RUN_ID" --run-attempt "$RUN_ATTEMPT" \
  --artifact-id "$ARTIFACT_ID" --shards 4
```

Obtain the three expected provider IDs independently from the selected run
and artifact, not from the reference JSON being checked. The planner
compares each ID to the digest-verified reference alongside
the source commit and archive digest.

The reference record uses exactly these keys:

| Key | Value |
| --- | --- |
| `schema` | `agent-os-root-timing-reference/1` |
| `repository` | `Blummer92/agent-os` |
| `source_head` | Full lowercase source commit SHA |
| `archive_sha256` | Lowercase provider SHA-256 for the original ZIP |
| `run_id`, `run_attempt`, `artifact_id` | Provider-verified positive JSON integers |
| `cases` | Rows of `[classname, name, tracked_repository_path]` |

The row inventory must come from a trusted source **independent of the report
being evaluated**. It must account for collection-skip rows, which have an
empty classname and an exact dotted module name. When a testcase has a
`file` attribute, it must equal the canonical tracked path in the inventory. A self-generated record
derived from the JUnit under review, a matching case count alone, and a
locally recomputed record checksum are not independent verification. This
offline program does not authenticate the provider or issuer itself; the
trusted reference digest is its trust input. If no independently verified
record exists for a historical run, do not replay it under this contract.

The ZIP must contain one regular top-level `root.xml` and use the supported
stored or deflated compression for that member. The XML profile is UTF-8
(optional BOM) with either a single `testsuite` or one direct suite inside
`testsuites`, nonempty itemized cases and consistent counts. No DTD or
entity declarations. Case durations accept 1–7 integer digits and an
optional fractional part of up to 9 digits, without exponent notation.
The planner adds exact integer nanoseconds and emits decimal strings. An
unsupported XML dialect or a missing expected row is a refusal, not a
partial plan. Exit 0 prints the timing model; exit 2 prints a fixed reason
to stderr. Help exits 0 and does not emit a model. No report bytes or local
paths are printed in a refusal.

The tool balances whole modules using their historical testcase time. The
model must not be used to exclude tests from current validation. Case time
excludes collection, imports, setup, queueing and evidence handling.

## Hosted benchmark (separate from the planner)

Compare the current aggregate against isolated three- and four-group runs on
the **same** trusted commit. Measure other package lanes separately. Keep
both independent full-root reference collections, Coach isolation, coverage,
JUnit/subtest and Black validation, provider head/run/attempt binding, and
one verdict.

Stop on missing, stale, duplicate, failed or out-of-inventory evidence.
Report queue-to-verdict and first-runner-start-to-verdict separately. Reject
the topology if outcomes, required test inventory, or negative controls
diverge. A local replay or fixture timing is not a hosted result.
