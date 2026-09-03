import json
from pathlib import Path

from agent_memory_context_manager.measurement import measured_reduction


FIXTURE = Path(__file__).parent / "fixtures" / "ckr4_hypothesis_benchmark.json"
FROZEN_TASK_IDS = tuple(f"T{index}" for index in range(1, 11))


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def observation(data, observation_id):
    return next(
        item for item in data["observations"]
        if item["observation_id"] == observation_id
    )


def test_frozen_t1_t10_task_ids_are_complete_and_unique():
    data = load_fixture()
    task_ids = tuple(item["task_id"] for item in data["tasks"])
    assert task_ids == FROZEN_TASK_IDS
    assert len(set(task_ids)) == 10


def test_observations_distinguish_unavailable_from_zero():
    data = load_fixture()
    post = observation(data, "post-tuning-C-positive")
    assert post["workspace_search_count"] == 0
    assert post["agent_step_count"] is None
    assert post["context_token_count"] is None


def test_ckr6a_candidate_and_noise_reductions_are_reproducible():
    data = load_fixture()
    before = observation(data, "pre-tuning-C-positive")
    after = observation(data, "post-tuning-C-positive")
    assert measured_reduction(before["candidate_count"], after["candidate_count"]) == 0.5
    assert measured_reduction(
        before["irrelevant_candidate_count"], after["irrelevant_candidate_count"]
    ) == 1.0


def test_equal_retrieval_call_counts_do_not_claim_reduction():
    data = load_fixture()
    before = observation(data, "pre-tuning-C-positive")
    after = observation(data, "post-tuning-C-positive")
    assert measured_reduction(
        before["notion_retrieval_count"], after["notion_retrieval_count"]
    ) == 0.0


def test_unavailable_token_or_step_metrics_cannot_produce_savings_claims():
    data = load_fixture()
    before = observation(data, "pre-tuning-C-positive")
    after = observation(data, "post-tuning-C-positive")
    assert measured_reduction(
        before["context_token_count"], after["context_token_count"]
    ) is None
    assert measured_reduction(
        before["agent_step_count"], after["agent_step_count"]
    ) is None
    assert measured_reduction(0, 0) is None


def test_benchmark_evidence_preserves_github_authority():
    data = load_fixture()
    assert all(
        item["source_authority"] == "github-canonical-notion-advisory"
        for item in data["observations"]
    )
    assert all(item["correctness"] == "pass" for item in data["observations"])
    assert all(item["safety"] == "pass" for item in data["observations"])
