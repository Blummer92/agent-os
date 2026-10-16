"""Benchmark harness tests. Fully offline; the live path runs only with fakes."""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_openrouter.benchmark import (
    CorpusError,
    LiveBenchmarkNotApproved,
    _corpus_entry_to_live_request,
    _derive_allowed_paths,
    _spend_ceiling_exceeded,
    default_corpus_path,
    load_corpus,
    run_benchmark,
    run_live_benchmark,
)
from scripts.agent_os_openrouter.config import (
    API_KEY_ENV_VAR,
    LIVE_BENCHMARK_ENV_VAR,
    OpenRouterConfig,
)
from scripts.agent_os_openrouter.pricing import OpenRouterPricingGateError

from ._helpers import TEST_API_KEY, FakeTransport, make_config, make_proposal_content

FREE_A = "vendor-a/model-a:free"
FREE_B = "vendor-b/model-b:free"


def test_corpus_loads_ten_entries():
    corpus = load_corpus(default_corpus_path())
    assert len(corpus) == 10
    numbers = [entry["issue_number"] for entry in corpus]
    assert len(set(numbers)) == 10


def test_corpus_entries_are_closed_verified_bugs():
    corpus = load_corpus(default_corpus_path())
    for entry in corpus:
        assert entry["state"] == "closed"
        assert len(entry["verified_root_cause"]) > 50
        assert entry["evidence_refs"]


def test_offline_run_computes_all_metrics():
    corpus = load_corpus(default_corpus_path())
    report = run_benchmark(corpus)
    assert len(report.bugs) == 10
    agg = report.aggregate
    assert agg.bugs_evaluated == 10
    # 2 of 20 model observations miss the verified root-cause key.
    assert agg.detection_accuracy == pytest.approx(18 / 20)
    assert agg.total_false_positives == 2
    # 19 of 20 observations carry a kernel-verifier ACCEPTED fixture.
    assert agg.kernel_verifier_accepted_rate == pytest.approx(19 / 20)
    assert agg.total_tokens_used == sum(
        t["tokens_used"]
        for entry in corpus
        for role in ("model_a", "model_b")
        for t in [entry["reference_transcript"][role]]
    )
    assert agg.total_estimated_cost_usd > 0
    assert agg.mean_time_to_root_cause_seconds is not None
    assert agg.mean_time_to_root_cause_seconds > 0
    payload = report.to_payload()
    assert payload["aggregate"]["bugs_evaluated"] == 10
    assert len(payload["bugs"]) == 10


def test_offline_run_uses_injectable_runner():
    corpus = load_corpus(default_corpus_path())
    seen = []

    def runner(entry, role):
        seen.append((entry["issue_number"], role))
        return dict(entry["reference_transcript"][role])

    report = run_benchmark(corpus, runner=runner)
    assert len(seen) == 20
    assert report.aggregate.bugs_evaluated == 10


def test_live_path_refuses_without_approval(monkeypatch):
    monkeypatch.delenv(LIVE_BENCHMARK_ENV_VAR, raising=False)
    corpus = load_corpus(default_corpus_path())
    with pytest.raises(LiveBenchmarkNotApproved):
        run_benchmark(corpus, live=True, config=OpenRouterConfig(enabled=True))


def test_live_path_refuses_without_keyed_config(monkeypatch):
    monkeypatch.setenv(LIVE_BENCHMARK_ENV_VAR, "true")
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)
    corpus = load_corpus(default_corpus_path())
    with pytest.raises(LiveBenchmarkNotApproved):
        run_benchmark(corpus, live=True, config=OpenRouterConfig(enabled=True))


def test_load_corpus_rejects_garbage(tmp_path):
    bad = tmp_path / "corpus.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CorpusError):
        load_corpus(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema_version": "1.0", "entries": []}), encoding="utf-8")
    with pytest.raises(CorpusError):
        load_corpus(empty)


# -- live benchmark runner (zero network: all transports are fakes) ---------


def _approved_env(monkeypatch):
    monkeypatch.setenv(LIVE_BENCHMARK_ENV_VAR, "true")
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)


def _live_config(**changes):
    values = dict(enabled=True, model_a=FREE_A, model_b=FREE_B,
                  max_retries=0, retry_backoff_seconds=0.0)
    values.update(changes)
    return OpenRouterConfig(**values)


def _free_catalog():
    return {
        "data": [
            {"id": FREE_A, "pricing": {"prompt": "0", "completion": "0"}},
            {"id": FREE_B, "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }


def _zero_cost_fetcher(gid):
    return {"data": [{"id": gid, "total_cost": 0}]}


def _live_envelope(entry, tokens=150):
    request = _corpus_entry_to_live_request(entry)
    return {
        "id": "gen-live-1",
        "choices": [{"message": {"role": "assistant",
                                "content": make_proposal_content(request)}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                  "total_tokens": tokens},
    }


def test_live_rejects_offline_runner(monkeypatch):
    _approved_env(monkeypatch)
    corpus = load_corpus(default_corpus_path())[:1]
    with pytest.raises(ValueError):
        run_benchmark(corpus, runner=lambda e, r: {}, live=True,
                      config=_live_config())


def test_live_full_run_two_bugs_records_pricing_evidence(monkeypatch):
    _approved_env(monkeypatch)
    corpus = [e for e in load_corpus(default_corpus_path())
              if e["issue_number"] in (3419, 3609)]
    assert len(corpus) == 2
    fake = FakeTransport([_live_envelope(corpus[0]), _live_envelope(corpus[0]),
                          _live_envelope(corpus[1]), _live_envelope(corpus[1])])
    report = run_live_benchmark(
        corpus, _live_config(), transport=fake,
        catalog_fetcher=_free_catalog, generation_cost_fetcher=_zero_cost_fetcher,
    )
    assert len(report.bugs) == 2
    for bug in report.bugs:
        for model_result in (bug.model_a, bug.model_b):
            assert model_result.outcome == "accepted", model_result.error
            assert model_result.reason_codes == ()
            assert model_result.plan_id is not None
            assert model_result.adapter_invoked is True
            assert model_result.error is None
            assert model_result.pricing_gate_defect is None
            # Pricing evidence verified pre-call, recorded per investigation.
            evidence = model_result.pricing_evidence
            assert evidence is not None
            assert evidence["model_id"] == model_result.model_identity
            assert evidence["model_id"].endswith(":free")
            assert evidence["prompt_price"] == "0"
            assert evidence["completion_price"] == "0"
            # Per-call cost verification: zero, recorded.
            cost = model_result.generation_cost_evidence
            assert cost is not None
            assert cost["generation_id"] == "gen-live-1"
            assert cost["total_cost"] == 0
            assert model_result.tokens_used == 150
            assert model_result.latency_seconds >= 0.0
    agg = report.aggregate
    assert agg.bugs_evaluated == 2
    assert agg.investigations_completed == 4
    assert agg.stopped_early is False
    assert agg.stop_reason is None
    assert agg.verifier_accepted_rate == pytest.approx(1.0)
    assert agg.total_verified_cost_usd == pytest.approx(0.0)
    assert agg.spend_ceiling_usd == pytest.approx(0.0)
    # Detection accuracy is honestly absent live: the model returns a plan,
    # not a root-cause key.
    assert agg.detection_accuracy is None
    assert agg.detection_adjudication == "pending-owner-review"
    payload = report.to_payload()
    assert len(payload["bugs"]) == 2
    assert payload["bugs"][0]["verified_root_cause_key"]


def test_live_request_never_leaks_verified_root_cause(monkeypatch):
    _approved_env(monkeypatch)
    corpus = [e for e in load_corpus(default_corpus_path())
              if e["issue_number"] == 3419]
    fake = FakeTransport([_live_envelope(corpus[0]), _live_envelope(corpus[0])])
    run_live_benchmark(
        corpus, _live_config(), transport=fake,
        catalog_fetcher=_free_catalog, generation_cost_fetcher=_zero_cost_fetcher,
    )
    entry = corpus[0]
    forbidden = (entry["verified_root_cause"], entry["verified_root_cause_key"],
                 entry["detection_criteria"])
    for call in fake.calls:
        body_text = json.dumps(call["body"])
        for secret in forbidden:
            assert secret not in body_text
        # The model identity sent is the exact :free identity, never stripped.
        assert call["body"]["model"] in (FREE_A, FREE_B)


def test_live_mid_run_paid_flip_stops_run_fail_closed(monkeypatch):
    _approved_env(monkeypatch)
    corpus = [e for e in load_corpus(default_corpus_path())
              if e["issue_number"] in (3419, 3609)]
    # Catalog sequence: the initial fetch, both pre-flight verifications,
    # and bug1's two invocation verifications are free; the bug2 model-A
    # re-fetch prices model A as paid -> its invocation fails closed.
    paid_flip = {
        "data": [
            {"id": FREE_A, "pricing": {"prompt": "0.01", "completion": "0"}},
            {"id": FREE_B, "pricing": {"prompt": "0", "completion": "0"}},
        ]
    }
    catalogs = [_free_catalog() for _ in range(5)] + [paid_flip]
    last = [_free_catalog()]

    def _refetch():
        last[0] = catalogs.pop(0) if catalogs else last[0]
        return last[0]

    fake = FakeTransport([_live_envelope(corpus[0]), _live_envelope(corpus[0]),
                          _live_envelope(corpus[1])])
    report = run_live_benchmark(
        corpus, _live_config(), transport=fake,
        catalog_fetcher=_refetch, generation_cost_fetcher=_zero_cost_fetcher,
    )
    assert report.aggregate.stopped_early is True
    assert "pricing-gate defect" in report.aggregate.stop_reason
    assert report.aggregate.bugs_evaluated == 2
    bug2 = report.bugs[1]
    # The kernel maps the gate exception to NEEDS_DECISION / provider.failure
    # with error=None; the defect flag is the runner-level signal.
    assert bug2.model_a.pricing_gate_defect.startswith("OpenRouterPricingGateError:")
    assert bug2.model_a.outcome == "needs-decision"
    assert bug2.model_a.reason_codes == ("provider.failure",)
    # No transport call was made for the defected invocation.
    assert len(fake.calls) == 3


def test_live_pre_flight_paid_model_raises_before_any_call(monkeypatch):
    _approved_env(monkeypatch)
    corpus = load_corpus(default_corpus_path())[:1]
    paid = {"data": [{"id": FREE_A, "pricing": {"prompt": "0.01", "completion": "0"}},
                     {"id": FREE_B, "pricing": {"prompt": "0", "completion": "0"}}]}
    fake = FakeTransport([])
    with pytest.raises(OpenRouterPricingGateError):
        run_live_benchmark(
            corpus, _live_config(), transport=fake,
            catalog_fetcher=lambda: paid, generation_cost_fetcher=_zero_cost_fetcher,
        )
    assert fake.calls == []


def test_live_initial_catalog_fetch_failure_fails_closed(monkeypatch):
    _approved_env(monkeypatch)
    corpus = load_corpus(default_corpus_path())[:1]

    def _boom():
        raise OSError("catalog unreachable")

    fake = FakeTransport([])
    with pytest.raises(OpenRouterPricingGateError):
        run_live_benchmark(
            corpus, _live_config(), transport=fake,
            catalog_fetcher=_boom, generation_cost_fetcher=_zero_cost_fetcher,
        )
    assert fake.calls == []


def test_live_generation_cost_defect_stops_run(monkeypatch):
    _approved_env(monkeypatch)
    corpus = [e for e in load_corpus(default_corpus_path())
              if e["issue_number"] in (3419, 3609)]

    def _paid_cost(gid):
        return {"data": [{"id": gid, "total_cost": 0.000003}]}

    fake = FakeTransport([_live_envelope(corpus[0]), _live_envelope(corpus[0])])
    report = run_live_benchmark(
        corpus, _live_config(), transport=fake,
        catalog_fetcher=_free_catalog, generation_cost_fetcher=_paid_cost,
    )
    assert report.aggregate.stopped_early is True
    assert "pricing-gate defect" in report.aggregate.stop_reason
    defect = report.bugs[0].model_a.pricing_gate_defect
    assert defect.startswith("OpenRouterPricingGateError:")
    assert "nonzero" in defect


def test_spend_ceiling_exceeded_predicate():
    assert _spend_ceiling_exceeded(0.05, 0.0) is True
    assert _spend_ceiling_exceeded(0.0, 0.0) is False
    assert _spend_ceiling_exceeded(0.03, 0.05) is False


def test_derive_allowed_paths_skips_urls_and_files():
    assert _derive_allowed_paths(
        ["https://github.com/x/y/issues/1", "tests/test_a.py", "08_Tooling/tool"]
    ) == ["08_Tooling/", "tests/"]
    assert _derive_allowed_paths(["validation_profiles.yml"]) == ["validation_profiles.yml"]
    assert _derive_allowed_paths(["https://example.com"]) == ["scripts/"]
    assert _derive_allowed_paths([]) == ["scripts/"]


def test_corpus_entry_to_live_request_is_kernel_valid():
    from scripts.agent_os_pr_remediation.high_reasoning_proposal import ProposalRequest

    corpus = load_corpus(default_corpus_path())
    for entry in corpus:
        request = _corpus_entry_to_live_request(entry)
        assert isinstance(request, ProposalRequest)
        assert request.source_sha == request.observed_source_sha
        assert request.compute_route == "high-reasoning-required"
        assert request.authorization_state == "authorized"
        assert request.authorization_fingerprint is not None
        # Deterministic: the same entry always builds the same request.
        twin = _corpus_entry_to_live_request(entry)
        assert request.request_fingerprint == twin.request_fingerprint
        assert request.source_sha == twin.source_sha
