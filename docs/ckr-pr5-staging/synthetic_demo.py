"""Toy generators, separate from the scorer; no production selector is invoked."""
import argparse
import json
import random

from evaluation import ARMS, CONTRACT, SHUFFLES, digest, freeze, missing, score, seal

def toy_revision(identity):
    return digest({"synthetic-lesson": identity, "revision": "frozen-v1"})

def planned_study():
    protocol = {"contract": CONTRACT, "baseline_sha": "fde87993061cb662cb10e85627833cdc4d69d668",
                "recipes": {a:digest({"toy-arm": a, "version": 1}) for a in ARMS},
                "min_cases": 24, "min_positives": 8, "min_hard_negatives": 8}
    cohort = {f"SYN-CASE-{i:02d}": {"eligible": [f"SYN-LESSON-{n}" for n in range(1,7)],
                                   "evidence": ["applicability", "ci"]}
              for i in range(1,26)}
    for case in cohort.values():
        case["revisions"] = {i:toy_revision(i) for i in case["eligible"]}
    cohort["SYN-CASE-25"]["evidence"].remove("ci")
    return protocol, cohort

def toy_result(arm, number, case, ordered_pool):
    if missing(case, arm):
        return dict(status="blocked", reason="required-evidence-missing", shortlist=[],
                    selected=[], revisions={}, tie_groups=[])
    # Exposed hand-built test paths—not empirically derived lessons/CI evidence.
    picked = None
    if number <= 8:
        picked = {"baseline": 1 if number == 1 else None,
                  "A": 1 if number <= 4 else None,
                  "B": 1 if number in (3, 5) else None,
                  "C": 1 if number <= 6 else None}[arm]
        if arm == "baseline" and number == 2:
            picked = 2
    if number == 9 and arm == "B":
        picked = 2
    if picked is None:
        return dict(status="abstained", reason="no-relevant-evidence", shortlist=[],
                    selected=[], revisions={}, tie_groups=[])
    # Every invocation sorts the actual shuffled input. The four tied low-scoring
    # candidates exercise stable equal-score ordering and a competing-budget cut.
    best = f"SYN-LESSON-{picked}"
    ordered = sorted(ordered_pool, key=lambda lesson: (lesson != best, lesson))
    shortlist = ordered[:5]
    return dict(status="selected", reason=None, shortlist=shortlist, selected=shortlist[:1],
                revisions={i:case["revisions"][i] for i in shortlist}, tie_groups=[shortlist[:1], shortlist[1:]])

def toy_outputs(protocol, cohort):
    outputs = {}
    for identity, case in cohort.items():
        number = int(identity.rsplit("-",1)[-1])
        pool = case["eligible"]
        order_by_shuffle = {}
        for seed in SHUFFLES:
            shuffled = pool[:]
            random.Random(seed).shuffle(shuffled)
            order_by_shuffle[str(seed)] = shuffled
        outputs[identity] = {}
        for arm in ARMS:
            outputs[identity][arm] = {
                "recipe": protocol["recipes"][arm], **toy_result(arm,number,case,pool),
                "shuffles": {seed:toy_result(arm,number,case,order)
                             for seed,order in order_by_shuffle.items()}}
    return outputs

def toy_labels(published):
    # Exposed structural fixture, neither independent oracle nor real gold.
    return {"sealed": published, "labels": {
        f"SYN-CASE-{i:02d}":{"kind":"positive" if i <= 8 or i == 25 else
                            ("hard-negative" if i <= 16 else "negative"),
                            "relevant": {"SYN-LESSON-1": toy_revision("SYN-LESSON-1")} if i <= 8 or i == 25 else {}}
        for i in range(1,26)}}

def run():
    protocol, cohort = planned_study()
    frozen = freeze(protocol, cohort)
    outputs = toy_outputs(protocol, cohort)
    published = seal(protocol, cohort, frozen, outputs)
    labels = toy_labels(published)
    return {"frozen": published, "result": score(protocol, cohort, frozen, outputs, published, labels)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()    # No input path or label-access interface.
    print(json.dumps(run(), indent=2, sort_keys=True, ensure_ascii=True))
