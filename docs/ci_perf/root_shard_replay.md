# Root suite sharding experiment

Goal: a three-minute workflow-to-verdict target, with five minutes the
maximum acceptable. Keep the current required gate in charge during the
experiment. This tool is an offline timing replay, not an Actions workflow,
a gate, or a replacement for test collection.

Use a provider-digest-verified JUnit archive and the commit that produced it:

```sh
python -m scripts.ci_perf.root_shard_replay \
  --archive junit-aggregate-1.zip --archive-sha256 "$ARTIFACT_SHA256" \
  --source-head "$SOURCE_HEAD" --shards 4
```

The tool maps every historical root JUnit row to a tracked test module at
the indicated commit and balances whole modules using summed testcase time.
Four groups on the #4143 reference were about 78 seconds each, before
collection, imports, runner setup, queueing and artifact verification.
The model must not be used to exclude tests from current validation.

The hosted experiment should compare the current aggregate against isolated
three- and four-group runs on the **same** trusted commit. Measure the
Execution Service and other package lanes separately. Keep both independent
full-root reference collections, Coach isolation, coverage, JUnit/subtest
and Black validation, provider head/run/attempt binding, and one verdict.
Stop on missing, stale, duplicate, failed or out-of-inventory evidence.
Report queue to verdict and first runner start to verdict separately.
Reject the topology if outcomes, required test inventory, or negative
controls diverge. A local replay or fixture timing is not a hosted result.
