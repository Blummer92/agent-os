"""Benchmark harness tests. Fully offline; the live path must always refuse."""

from __future__ import annotations

import json

import pytest

from scripts.agent_os_openrouter.benchmark import (
    CorpusError,
    LiveBenchmarkNotApproved,
    LiveBenchmarkNotExecuted,
    default_corpus_path,
    load_corpus,
    run_benchmark,
)
from scripts.agent_os_openrouter.config import (
    API_KEY_ENV_VAR,
    LIVE_BENCHMARK_ENV_VAR,
    OpenRouterConfig,
)

from ._helpers import TEST_API_KEY


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


def test_live_path_never_executes_even_when_approved(monkeypatch):
    # Both gates pass, yet the live comparison is prepared-but-unexecuted:
    # the harness raises instead of calling the network.
    monkeypatch.setenv(LIVE_BENCHMARK_ENV_VAR, "true")
    monkeypatch.setenv("OPENROUTER_PILOT_ENABLED", "true")
    monkeypatch.setenv(API_KEY_ENV_VAR, TEST_API_KEY)
    corpus = load_corpus(default_corpus_path())
    with pytest.raises(LiveBenchmarkNotExecuted):
        run_benchmark(corpus, live=True, config=OpenRouterConfig.from_env())


def test_load_corpus_rejects_garbage(tmp_path):
    bad = tmp_path / "corpus.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CorpusError):
        load_corpus(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"schema_version": "1.0", "entries": []}), encoding="utf-8")
    with pytest.raises(CorpusError):
        load_corpus(empty)
