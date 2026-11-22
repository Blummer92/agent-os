from copy import deepcopy

import pytest

from evaluation import ARMS, digest, freeze, score, seal
from synthetic_demo import planned_study, run, toy_labels, toy_outputs, toy_revision

@pytest.fixture
def pack():
    protocol, cohort = planned_study()
    frozen = freeze(protocol, cohort)
    outputs = toy_outputs(protocol, cohort)
    published = seal(protocol,cohort,frozen,outputs)
    return protocol, cohort, frozen, outputs, published, toy_labels(published)

def rerun(pack):
    p,c,f,o,_,_ = pack
    s = seal(p,c,f,o)
    return score(p,c,f,o,s,toy_labels(s))

def test_synthetic_summary_denominators_and_boundaries(pack):
    r = score(*pack)
    assert r["ranking_authorized"] is False and r["study_acceptance"] == "not-evaluated"
    assert r["total_cases"] == 25 and len(r["common_case_ids"]) == 24
    assert r["common_by_label"] == {"positive": 8, "hard-negative": 8, "negative": 8}
    assert r["overall_by_label"] == {"positive": 9, "hard-negative": 8, "negative": 8}
    assert r["excluded_from_common"] == {
        "SYN-CASE-25": {"B":"required-evidence-missing", "C":"required-evidence-missing"}}
    assert r["common_minima_met"] and not r["violations"]
    assert r["metrics_available_only"]["baseline"]["positive_cases"] == 9
    assert r["metrics_available_only"]["A"]["positive_cases"] == 9
    assert r["metrics_available_only"]["B"]["positive_cases"] == 8
    assert set(v["case_count"] for v in r["metrics_common"].values()) == {24}
    assert r["flow"]["C"]["required-evidence-missing"] == 1
    assert r["missing_evidence"]["B"] == {"ci":1}
    assert r["metrics_common"]["C"]["abstentions"] == 18
    assert r["metrics_common"]["baseline"]["micro_precision_at_3"] == {
        "numerator": 1, "denominator": 2, "value": 0.5}
    assert r["metrics_common"]["C"]["micro_recall_at_3"] == {
        "numerator": 6, "denominator": 8, "value": 0.75}
    assert r["metrics_common"]["baseline"]["false_abstentions"] == 6   # wrong pick not abstention
    assert r["metrics_common"]["B"]["hard_negative_false_positive_rate"] == {
        "numerator": 1, "denominator": 8, "value": .125}
    assert r["paired_common"]["C_vs_A"] == {
      "gains":2, "losses":0, "both_hit":4, "both_miss":2, "positive_denominator":8,
      "removed_false_abstentions":2, "new_false_abstentions":0,
      "new_hard_negative_false_positives":0, "removed_hard_negative_false_positives":0, "hard_negative_denominator":8}

@pytest.mark.parametrize("member", ["protocol", "cohort", "outputs", "label-frame"])
def test_postfreeze_drift_rejected(pack, member):
    p,c,f,o,s,l = deepcopy(pack)
    if member == "protocol":
        p["min_cases"] = 25
    elif member == "cohort":
        c["SYN-CASE-25"]["eligible"].append("SYN-LESSON-7")
        c["SYN-CASE-25"]["revisions"]["SYN-LESSON-7"] = toy_revision("SYN-LESSON-7")
    elif member == "outputs":
        o["SYN-CASE-01"]["baseline"]["status"] = "abstained"
    else:
        l["sealed"] = {"protocol_digest": s["protocol_digest"]}
    with pytest.raises(ValueError, match="freeze-mismatch|output-seal-mismatch|labels-frame-mismatch"):
        score(p,c,f,o,s,l)

def test_adjacent_baseline_pin_cannot_reuse_freeze(pack):
    p,c,f,o,s,l = deepcopy(pack)
    p["baseline_sha"] = "1"*40
    with pytest.raises(ValueError, match="freeze-mismatch"):
        score(p,c,f,o,s,l)

@pytest.mark.parametrize("bad", [True, 0, -1, 501, "24"])
def test_malformed_pilot_minimum_rejected(pack, bad):
    p,c,*_ = pack
    p["min_cases"] = bad
    with pytest.raises(ValueError, match="bad-minimum"):
        freeze(p,c)

def test_full_intake_meets_length_but_common_cohort_fails(pack):
    p,c,*_ = pack
    p["min_cases"] = 25
    f = freeze(p,c)
    o = toy_outputs(p,c)
    r = rerun((p,c,f,o,None,None))
    assert not r["common_minima_met"] and r["total_cases"] == 25 and len(r["common_case_ids"]) == 24

@pytest.mark.parametrize("missing_output", ["case", "arm", "shuffle"])
def test_require_exact_output_coverage(pack, missing_output):
    p,c,f,o,*_ = pack
    if missing_output == "case":
        o.pop("SYN-CASE-25")
    elif missing_output == "arm":
        o["SYN-CASE-25"].pop("B")
    else:
        o["SYN-CASE-25"]["B"]["shuffles"].pop("9")
    with pytest.raises(ValueError, match="output-case-mismatch|wrong-fields"):
        seal(p,c,f,o)

def test_transposed_arm_recipe_rejected(pack):
    p,c,f,o,*_ = pack
    o["SYN-CASE-01"]["A"]["recipe"] = p["recipes"]["B"]
    with pytest.raises(ValueError, match="bad-arm-result"):
        seal(p,c,f,o)

@pytest.mark.parametrize("change,expect", [
    ("budget", "budget-exceeded"), ("not-prefix", "not-ranked-prefix"),
    ("tie-order", "unstable-equal-score-order"), ("tie-hole", "tie-groups-do-not-partition-shortlist"),
    ("ineligible", "ineligible-recommendation"), ("only-shuffle", "shuffle-output-changed"),
])
def test_invalid_ranking_does_not_create_comparable_case(pack, change, expect):
    p,c,f,o,*_ = pack
    row = o["SYN-CASE-01"]["C"]
    if change == "only-shuffle":
        row["shuffles"]["9"]["reason"] = "ambiguous-tie"
    else:
        for receipt in (row, *row["shuffles"].values()):
            if change == "budget":
                receipt["shortlist"].append("SYN-LESSON-6")
                receipt["revisions"]["SYN-LESSON-6"] = toy_revision("SYN-LESSON-6")
                receipt["selected"] = receipt["shortlist"][:4]
            if change == "not-prefix":
                receipt["selected"] = receipt["shortlist"][1:2]
            if change == "tie-order":
                receipt["shortlist"][1:] = receipt["shortlist"][1:][::-1]
            if change == "ineligible":
                receipt["revisions"].pop(receipt["shortlist"][0])
                receipt["shortlist"][0] = receipt["selected"][0] = "SYN-LESSON-99"
                receipt["revisions"]["SYN-LESSON-99"] = toy_revision("SYN-LESSON-99")
            if change != "tie-hole":
                receipt["tie_groups"] = [receipt["shortlist"][:1],receipt["shortlist"][1:]]
            else:
                receipt["tie_groups"].pop()
    r = rerun(pack)
    assert expect in {v["code"] for v in r["violations"]["SYN-CASE-01"]["C"]}
    assert "SYN-CASE-01" not in r["common_case_ids"] and not r["common_minima_met"]
    assert r["flow"]["C"]["invalid"] == 1

def test_missing_evidence_masquerading_as_abstention_does_not_count(pack):
    row = pack[3]["SYN-CASE-25"]["C"]
    for receipt in (row, *row["shuffles"].values()):
        receipt.update(status="abstained",reason="ambiguous-tie")
    r = rerun(pack)
    assert r["flow"]["C"]["invalid"] == 1
    assert r["metrics_available_only"]["C"]["positive_cases"] == 8
    assert "missing-evidence-accepted" in {v["code"] for v in r["violations"]["SYN-CASE-25"]["C"]}

def test_runner_unavailable_is_distinct_from_missing_evidence(pack):
    row = pack[3]["SYN-CASE-01"]["A"]
    for receipt in (row, *row["shuffles"].values()):
        receipt.update(status="blocked",reason="runner-unavailable",shortlist=[],selected=[],revisions={},tie_groups=[])
    r = rerun(pack)
    assert r["flow"]["A"]["runner-unavailable"] == 1
    assert r["missing_evidence"]["A"] == {} and not r["violations"]
    assert r["metrics_common"]["A"]["positive_cases"] == 7

def test_label_gold_outside_candidate_pool_remains_recall_miss(pack):
    p,c,f,o,s,l = pack
    l["labels"]["SYN-CASE-08"]["relevant"]["SYN-LESSON-99"] = toy_revision("SYN-LESSON-99")
    r = score(*pack)
    assert r["metrics_common"]["C"]["micro_recall_at_3"]["denominator"] == 9

@pytest.mark.parametrize("labels", ["empty", "missing-case", "contradict-negative", "not-synthetic"])
def test_malformed_labels_rejected(pack, labels):
    p,c,f,o,s,l = pack
    if labels == "empty":
        l["labels"]["SYN-CASE-01"]["relevant"] = {}
    elif labels == "missing-case":
        l["labels"].pop("SYN-CASE-01")
    elif labels == "contradict-negative":
        l["labels"]["SYN-CASE-09"]["relevant"] = {"SYN-LESSON-1": toy_revision("SYN-LESSON-1")}
    else:
        l["labels"]["SYN-CASE-01"]["relevant"] = {"LL-1": toy_revision("LL-1")}
    with pytest.raises(ValueError, match="invalid-label-polarity|label-case-mismatch|bad-label"):
        score(*pack)

def test_empty_common_returns_undefined_metrics(pack):
    p,c,f,o,*_ = pack
    for case in c.values():
        case["evidence"] = []
    f = freeze(p,c)
    o = toy_outputs(p,c)
    r = rerun((p,c,f,o,None,None))
    assert r["common_case_ids"] == [] and not r["common_minima_met"]
    for arm in ARMS:
        assert r["metrics_common"][arm]["micro_recall_at_3"] == {
            "numerator":0,"denominator":0,"value":None}

def test_semantic_digest_and_complete_demo_reproducible(pack):
    p,c,*_ = pack
    assert digest(dict(reversed(tuple(p.items())))) == digest(p)
    assert run() == run()

def test_exact_pair_does_not_credit_same_id_with_different_gold_revision(pack):
    p,c,f,o,s,l = pack
    label = l["labels"]["SYN-CASE-01"]["relevant"]
    label["SYN-LESSON-1"] = digest({"synthetic-preregistration": "different-revision"})
    r = score(p,c,f,o,s,l)
    before = r["metrics_common"]["baseline"]
    assert before["positive_hits"] == 0 and before["recommended"] == 2
    assert before["micro_recall_at_3"]["denominator"] == 8
    assert not r["violations"]    # the selector returned the frozen eligible revision
    assert len(r["common_case_ids"]) == 24

def test_output_older_revision_is_invalid_not_an_abstention(pack):
    case = "SYN-CASE-01"
    row = pack[3][case]["baseline"]
    for receipt in (row, *row["shuffles"].values()):
        receipt["revisions"]["SYN-LESSON-1"] = digest({"returned": "old-revision"})
    r = rerun(pack)
    assert r["flow"]["baseline"]["invalid"] == 1
    assert r["excluded_from_common"][case] == {"baseline":"invalid"}
    assert all(x["code"] == "shortlist-revision-mismatch" for x in r["violations"][case]["baseline"])
    assert r["metrics_common"]["baseline"]["false_abstentions"] == 6

def test_malformed_revision_rejected_at_three_boundaries(pack):
    p,c,f,o,s,l = pack
    broken = deepcopy(c)
    del broken["SYN-CASE-01"]["revisions"]["SYN-LESSON-1"]
    with pytest.raises(ValueError,match="bad-frozen-revisions"):
        freeze(p,broken)
    broken = deepcopy(o)
    del broken["SYN-CASE-01"]["baseline"]["revisions"]["SYN-LESSON-1"]
    with pytest.raises(ValueError,match="bad-output-revisions"):
        seal(p,c,f,broken)
    l["labels"]["SYN-CASE-01"]["relevant"]["SYN-LESSON-1"] = "latest"
    with pytest.raises(ValueError,match="bad-label"):
        score(p,c,f,o,s,l)

def test_same_identity_with_changed_frozen_revision_requires_refreeze(pack):
    p,c,f,o,s,l = pack
    c["SYN-CASE-01"]["revisions"]["SYN-LESSON-1"] = digest({"frozen": "new"})
    with pytest.raises(ValueError,match="freeze-mismatch"):
        score(p,c,f,o,s,l)

def test_order_replay_revision_drift_detected_even_when_id_does_not_change(pack):
    receipt = pack[3]["SYN-CASE-01"]["baseline"]["shuffles"]["9"]
    receipt["revisions"]["SYN-LESSON-1"] = digest({"changed": "one-shuffle-revision"})
    r = rerun(pack)
    assert {err["code"] for err in r["violations"]["SYN-CASE-01"]["baseline"]} == {
        "shortlist-revision-mismatch", "shuffle-output-changed"}


@pytest.mark.parametrize("reorder", ["shuffles", "labels"])
def test_equal_output_seals_emit_same_ordered_violation_report(pack, reorder):
    """Equivalent JSON objects can arrive with different replay-key order."""
    import json

    p, c, f, original, _, _ = pack
    row = original["SYN-CASE-01"]["baseline"]
    row["shuffles"]["2"]["revisions"]["SYN-LESSON-1"] = digest({"stale": 2})
    row["shuffles"]["7"]["revisions"]["SYN-LESSON-1"] = digest({"stale": 7})
    reordered = deepcopy(original)
    if reorder == "shuffles":
        replay = reordered["SYN-CASE-01"]["baseline"]
        replay["shuffles"] = dict(reversed(tuple(replay["shuffles"].items())))
    prior_seal = seal(p, c, f, original)
    assert seal(p, c, f, reordered) == prior_seal
    labels = toy_labels(prior_seal)
    before = score(p, c, f, original, prior_seal, labels)
    if reorder == "labels":
        labels["labels"] = dict(reversed(tuple(labels["labels"].items())))
    after = score(p, c, f, reordered, prior_seal, labels)
    assert json.dumps(before) == json.dumps(after)
    errors = after["violations"]["SYN-CASE-01"]["baseline"]
    assert [item["case_order"] for item in errors] == ["2", "2", "7", "7"]


@pytest.mark.parametrize(
    "extra_shortlist, selected_count, admissible",
    [(False, 3, True), (False, 4, False), (True, 3, False)],
)
def test_candidate_and_selection_caps_independent(pack, extra_shortlist, selected_count, admissible):
    case = "SYN-CASE-01"
    row = pack[3][case]["C"]
    for receipt in (row, *row["shuffles"].values()):
        if extra_shortlist:
            receipt["shortlist"].append("SYN-LESSON-6")
            receipt["revisions"]["SYN-LESSON-6"] = toy_revision("SYN-LESSON-6")
        receipt["selected"] = receipt["shortlist"][:selected_count]
        receipt["tie_groups"] = [receipt["shortlist"][:1], receipt["shortlist"][1:]]
    result = rerun(pack)
    if admissible:
        assert case in result["common_case_ids"]
        assert result["metrics_common"]["C"]["recommended"] == 8
        assert case not in result["violations"]
    else:
        assert case not in result["common_case_ids"]
        assert {error["code"] for error in result["violations"][case]["C"]} == {"budget-exceeded"}


def test_independent_thresholds_accept_a_feasible_protocol(pack):
    """A total-case floor is not a cap on the two disjoint class floors."""
    p, c, *_ = pack
    p["min_cases"] = 12
    f = freeze(p, c)
    r = rerun((p, c, f, toy_outputs(p, c), None, None))
    assert len(r["common_case_ids"]) == 24
    assert r["common_by_label"]["positive"] == r["common_by_label"]["hard-negative"] == 8
    assert r["common_minima_met"]


def test_impossible_disjoint_class_minima_still_rejected(pack):
    from evaluation import MAX_CASES

    p, c, *_ = pack
    p.update(min_cases=MAX_CASES - 3, min_positives=MAX_CASES - 1, min_hard_negatives=2)
    with pytest.raises(ValueError, match="infeasible-minimum"):
        freeze(p, c)


@pytest.mark.parametrize("eligible", [[], ["SYN-LESSON-2", "SYN-LESSON-3"]])
def test_demo_never_substitutes_another_lesson_for_missing_planned_lesson(pack, eligible):
    p, c, *_ = pack
    identity = "SYN-CASE-01"
    case = c[identity]
    case["eligible"] = eligible
    case["revisions"] = {item: case["revisions"][item] for item in eligible}
    f = freeze(p, c)
    o = toy_outputs(p, c)
    r = rerun((p, c, f, o, None, None))
    expected = dict(status="abstained", reason="no-relevant-evidence", shortlist=[],
                    selected=[], revisions={}, tie_groups=[])
    for arm in ("baseline", "A", "C"):
        row = o[identity][arm]
        assert {key: row[key] for key in expected} == expected
        assert all(replay == expected for replay in row["shuffles"].values())
    assert identity in r["common_case_ids"] and not r["violations"]
    assert r["metrics_common"]["baseline"]["positive_hits"] == 0
    assert r["metrics_common"]["baseline"]["false_abstentions"] == 7


def test_demo_single_eligible_best_does_not_create_an_empty_tie_group(pack):
    p, c, *_ = pack
    identity = "SYN-CASE-01"
    case = c[identity]
    best = "SYN-LESSON-1"
    case["eligible"] = [best]
    case["revisions"] = {best: case["revisions"][best]}
    f = freeze(p, c)
    o = toy_outputs(p, c)
    r = rerun((p, c, f, o, None, None))
    row = o[identity]["baseline"]
    assert row["selected"] == [best]
    assert row["tie_groups"] == [[best]]
    assert r["metrics_common"]["baseline"]["positive_hits"] == 1
    assert not r["violations"]


def test_paired_metrics_use_overlap_not_the_union_of_arm_successes(pack):
    p, original, *_ = pack
    identities = [f"SYN-CASE-0{number}" for number in (1, 2, 3)]
    c = {key: original[key] for key in identities}
    f = freeze(p, c)
    o = toy_outputs(p, c)
    for arm, identity in (("A", identities[2]), ("C", identities[0])):
        row = o[identity][arm]
        for receipt in (row, *row["shuffles"].values()):
            receipt.update(status="blocked", reason="runner-unavailable", shortlist=[],
                           selected=[], tie_groups=[], revisions={})
    s = seal(p, c, f, o)
    l = toy_labels(s)
    l["labels"] = {key: l["labels"][key] for key in identities}
    r = score(p, c, f, o, s, l)
    assert r["common_case_ids"] == [identities[1]]
    assert not r["common_minima_met"] and not r["violations"]
    assert all(r["metrics_available_only"][arm]["positive_hits"] == 2 for arm in ("A", "C"))
    pairing = r["paired_common"]["C_vs_A"]
    assert pairing["positive_denominator"] == pairing["both_hit"] == 1
    assert pairing["gains"] == pairing["losses"] == 0


def test_exact_revision_in_position_four_does_not_count_as_top_three(pack):
    p, c, f, original, _, _ = pack
    identity = "SYN-CASE-01"

    def run_three(order):
        o = deepcopy(original)
        row = o[identity]["C"]
        for receipt in (row, *row["shuffles"].values()):
            receipt.update(shortlist=order, selected=order[:3], tie_groups=[[item] for item in order])
        s = seal(p, c, f, o)
        l = toy_labels(s)
        l["labels"][identity]["relevant"] = {"SYN-LESSON-4": toy_revision("SYN-LESSON-4")}
        return s, score(p, c, f, o, s, l)

    ordered = [f"SYN-LESSON-{position}" for position in range(1, 6)]
    old, before = run_three(ordered)
    ordered[2], ordered[3] = ordered[3], ordered[2]
    new, after = run_three(ordered)
    assert old["outputs_digest"] != new["outputs_digest"]
    assert old["cohort_digest"] == new["cohort_digest"] and not before["violations"] and not after["violations"]
    b, a = (r["metrics_common"]["C"] for r in (before, after))
    assert b["recommended"] == a["recommended"] and a["relevant_recommended"] == b["relevant_recommended"] + 1
    assert after["paired_common"]["C_vs_A"]["gains"] == before["paired_common"]["C_vs_A"]["gains"] + 1


def test_roster_key_order_changes_neither_seal_nor_report_bytes(pack):
    import json

    p, c, f, o, s, l = pack
    rev = lambda obj: dict(reversed(tuple(obj.items())))
    assert freeze(p, rev(c)) == f and seal(p, rev(c), f, rev(o)) == s
    assert json.dumps(score(p, c, f, o, s, l)) == json.dumps(score(p, rev(c), f, rev(o), s, l))
