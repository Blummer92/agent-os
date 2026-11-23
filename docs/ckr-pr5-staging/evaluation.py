"""Synthetic-only paired ranking evaluation. Never runs or changes a selector."""
from collections import Counter
import hashlib
import json
import re

ARMS = ("baseline", "A", "B", "C")
SHUFFLES = tuple(range(10))
SIGNALS = {"baseline": (), "A": ("applicability",), "B": ("ci",), "C": ("applicability", "ci")}
AVAILABLE = frozenset(("applicability", "ci"))
CONTRACT = "ckr-pr5-synthetic-ranking-v2"
MAX_CASES = 500
CANDIDATE_CAP = 5
SELECTION_CAP = 3
MAX_POOL = 500
LABELS = ("positive", "hard-negative", "negative")
RESULTS = ("selected", "abstained", "blocked")
HASH_RE = re.compile(r"[0-9a-f]{64}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SYN_RE = re.compile(r"SYN-[A-Z0-9][A-Z0-9_-]{0,62}")

def require(ok, code):
    if not ok:
        raise ValueError(code)

def digest(obj):
    """Semantic equality receipt for strict finite JSON, not authentication."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()

def exact(obj, fields):
    require(type(obj) is dict and set(obj) == set(fields.split()), "wrong-fields")

def is_hex(value, pattern=HASH_RE):
    return type(value) is str and pattern.fullmatch(value) is not None

def synthetic(value):
    return is_hex(value, SYN_RE)

def identifiers(values, limit):
    return (type(values) is list and len(values) <= limit and
            all(synthetic(x) for x in values) and len(set(values)) == len(values))

def revision_map(values, identities=None):
    return (type(values) is dict and len(values) <= MAX_POOL and
            all(synthetic(identity) and is_hex(revision) for identity, revision in values.items())
            and (identities is None or set(values) == set(identities)))

def protocol_check(protocol):
    exact(protocol, "contract baseline_sha recipes min_cases min_positives min_hard_negatives")
    require(protocol["contract"] == CONTRACT and is_hex(protocol["baseline_sha"], SHA_RE), "bad-protocol")
    exact(protocol["recipes"], "baseline A B C")
    for recipe in protocol["recipes"].values():
        require(is_hex(recipe), "bad-recipe-digest")
    require(len(set(protocol["recipes"].values())) == len(ARMS), "duplicate-recipe-digests")
    for name in ("min_cases", "min_positives", "min_hard_negatives"):
        require(type(protocol[name]) is int and 0 < protocol[name] <= MAX_CASES, "bad-minimum")
    # The total floor can be lower than the sum of the disjoint class floors.
    require(protocol["min_positives"] + protocol["min_hard_negatives"] <= MAX_CASES,
            "infeasible-minimum")

def cohort_check(cohort):
    require(type(cohort) is dict and 0 < len(cohort) <= MAX_CASES, "bad-cohort-size")
    for identity, case in cohort.items():
        require(synthetic(identity), "not-synthetic-case")
        exact(case, "eligible revisions evidence")
        require(identifiers(case["eligible"], MAX_POOL), "bad-eligible-pool")
        require(revision_map(case["revisions"], case["eligible"]), "bad-frozen-revisions")
        require(type(case["evidence"]) is list and len(case["evidence"]) <= len(AVAILABLE) and
                all(type(x) is str and x in AVAILABLE for x in case["evidence"]) and
                len(set(case["evidence"])) == len(case["evidence"]), "bad-evidence-list")

def freeze(protocol, cohort):
    """Freeze the shared eligible pools, availability, and recipe identities without labels."""
    protocol_check(protocol)
    cohort_check(cohort)
    return {"protocol_digest": digest(protocol), "cohort_digest": digest(cohort)}

def missing(case, arm):
    return sorted(set(SIGNALS[arm]) - set(case["evidence"]))

def _validate_row(row, recipe):
    exact(row, "recipe status reason shortlist selected revisions tie_groups shuffles")
    require(row["recipe"] == recipe and row["status"] in RESULTS, "bad-arm-result")
    exact(row["shuffles"], " ".join(map(str, SHUFFLES)))
    # Allow finite malformed order/budget shapes to be reported as violations rather
    # than counted as normal success. Unknown identifiers still fail schema.
    for receipt in (row, *row["shuffles"].values()):
        if receipt is not row:
            exact(receipt, "status reason shortlist selected revisions tie_groups")
        require(receipt["status"] in RESULTS, "bad-arm-status")
        require(identifiers(receipt["shortlist"], MAX_POOL) and
                identifiers(receipt["selected"], MAX_POOL), "bad-output-identifiers")
        require(revision_map(receipt["revisions"], receipt["shortlist"]), "bad-output-revisions")
        require(type(receipt["tie_groups"]) is list and len(receipt["tie_groups"]) <= MAX_POOL and
                all(identifiers(group, MAX_POOL) and group for group in receipt["tie_groups"]) and
                sum(map(len, receipt["tie_groups"])) <= MAX_POOL, "bad-tie-groups")
        require(receipt["reason"] in (None, "no-relevant-evidence", "ambiguous-tie",
                                      "required-evidence-missing", "runner-unavailable"),
                "bad-reason-code")

def seal(protocol, cohort, frozen, outputs):
    """Validate arm receipt shape and bind output bytes before synthetic scoring."""
    require(frozen == freeze(protocol, cohort), "freeze-mismatch")
    require(type(outputs) is dict and set(outputs) == set(cohort), "output-case-mismatch")
    for identity, rows in outputs.items():
        exact(rows, "baseline A B C")
        for arm, row in rows.items():
            _validate_row(row, protocol["recipes"][arm])
    return {**frozen, "outputs_digest": digest(outputs)}

def _validate_labels(cohort, published, labels):
    exact(labels, "sealed labels")
    require(labels["sealed"] == published, "labels-frame-mismatch")
    values = labels["labels"]
    require(type(values) is dict and set(values) == set(cohort), "label-case-mismatch")
    for identity, label in values.items():
        exact(label, "kind relevant")
        require(label["kind"] in LABELS and revision_map(label["relevant"]), "bad-label")
        require(bool(label["relevant"]) == (label["kind"] == "positive"), "invalid-label-polarity")
        # Do not silently erase a relevance/coverage miss if the common eligible
        # pool lacks a gold lesson. The independent oracle can mark it relevant.
    return values

def _invariants(row, case, arm):
    errors = []
    required = missing(case, arm)
    projection = {k: row[k] for k in ("status", "reason", "shortlist", "selected", "revisions", "tie_groups")}
    # Seal ignores JSON object key order; the diagnostic list must do so too.
    for seed, receipt in (("primary", projection), *sorted(row["shuffles"].items())):
        status, reason = receipt["status"], receipt["reason"]
        shortlist, selected, groups = (receipt[k] for k in ("shortlist", "selected", "tie_groups"))
        flags = []
        if required and (status != "blocked" or reason != "required-evidence-missing"):
            flags.append("missing-evidence-accepted")
        if not required and reason == "required-evidence-missing":
            flags.append("evidence-present-misclassified")
        if status == "selected" and (not selected or reason is not None):
            flags.append("selected-status-inconsistent")
        if status == "abstained" and (selected or reason not in ("no-relevant-evidence", "ambiguous-tie")):
            flags.append("abstention-status-inconsistent")
        if status == "blocked" and (selected or shortlist or groups or
                                    reason not in ("required-evidence-missing", "runner-unavailable")):
            flags.append("blocked-status-inconsistent")
        if len(shortlist) > CANDIDATE_CAP or len(selected) > SELECTION_CAP:
            flags.append("budget-exceeded")
        if not set(shortlist) <= set(case["eligible"]):
            flags.append("ineligible-recommendation")
        if any(receipt["revisions"][i] != case["revisions"][i]
               for i in shortlist if i in case["revisions"]):
            flags.append("shortlist-revision-mismatch")
        if selected != shortlist[:len(selected)]:
            flags.append("not-ranked-prefix")
        if [value for group in groups for value in group] != shortlist:
            flags.append("tie-groups-do-not-partition-shortlist")
        if any(group != sorted(group) for group in groups):
            flags.append("unstable-equal-score-order")
        if seed != "primary" and receipt != projection:
            flags.append("shuffle-output-changed")
        errors.extend({"case_order": seed, "code": code} for code in flags)
    return errors

def _ratio(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}

def _hits(row, label):
    return sum(row["revisions"][i] == label["relevant"].get(i) for i in row["selected"])

def _measure(ids, arm, outputs, labels, primary):
    observed = Counter()
    for identity in ids:
        row = outputs[identity][arm]
        label = labels[identity]
        selected = row["selected"]  # Only measured, budget-checked rows reach here.
        relevant = label["relevant"]
        hits = _hits(row,label)
        observed["case_count"] += 1
        observed["positive_cases"] += label["kind"] == "positive"
        observed["hard_negatives"] += label["kind"] == "hard-negative"
        observed["selected_cases"] += row["status"] == "selected"
        observed["abstentions"] += row["status"] == "abstained"
        observed["false_abstentions"] += bool(relevant) and row["status"] == "abstained"
        observed["positive_hits"] += bool(hits)
        observed["recommended"] += len(selected)
        observed["relevant_recommended"] += hits
        observed["relevant_total"] += len(relevant)
        observed["hard_negative_false_positives"] += (label["kind"] == "hard-negative" and bool(selected))
        observed["negative_false_positives"] += (label["kind"] != "positive" and bool(selected))
    fields = ("case_count", "positive_cases", "hard_negatives", "selected_cases", "abstentions",
              "false_abstentions", "positive_hits", "recommended", "relevant_recommended",
              "relevant_total", "hard_negative_false_positives", "negative_false_positives")
    counts = {field: observed[field] for field in fields}
    return {"primary_common_cohort": primary, **counts,
            "micro_precision_at_3": _ratio(observed["relevant_recommended"], observed["recommended"]),
            "micro_recall_at_3": _ratio(observed["relevant_recommended"], observed["relevant_total"]),
            "positive_hit_rate": _ratio(observed["positive_hits"], observed["positive_cases"]),
            "false_abstention_rate": _ratio(observed["false_abstentions"], observed["positive_cases"]),
            "hard_negative_false_positive_rate": _ratio(observed["hard_negative_false_positives"],
                                                       observed["hard_negatives"])}

def score(protocol, cohort, frozen, outputs, published, labels):
    """Report coverage and paired metrics. No result from this toy can authorize PR5."""
    require(seal(protocol, cohort, frozen, outputs) == published, "output-seal-mismatch")
    labels_by_case = _validate_labels(cohort, published, labels)
    violations = {}
    measured = {arm: [] for arm in ARMS}
    excluded = {}
    flow = {arm: Counter() for arm in ARMS}
    missing_evidence = {arm: Counter() for arm in ARMS}
    ordered_cases = sorted(cohort)
    for identity in ordered_cases:
        for arm in ARMS:
            row, case = outputs[identity][arm], cohort[identity]
            errors = _invariants(row, case, arm)
            missing_evidence[arm].update(missing(case, arm))
            if errors:
                flow[arm]["invalid"] += 1
                excluded.setdefault(identity, {})[arm] = "invalid"
                violations.setdefault(identity, {})[arm] = errors
            elif row["status"] == "blocked":
                flow[arm][row["reason"]] += 1
                excluded.setdefault(identity, {})[arm] = row["reason"]
            else:
                flow[arm][row["status"]] += 1
                measured[arm].append(identity)
    common = sorted(set.intersection(*(set(measured[a]) for a in ARMS)))
    common_kind = Counter(labels_by_case[x]["kind"] for x in common)
    minimums = (len(common) >= protocol["min_cases"] and
                common_kind["positive"] >= protocol["min_positives"] and
                common_kind["hard-negative"] >= protocol["min_hard_negatives"])
    # Compare gains and losses on the very same positive common cases.
    paired = {}
    for lhs, rhs in (("baseline", "A"), ("baseline", "B"), ("baseline", "C"), ("A", "C")):
        wins = {"gains": 0, "losses": 0, "both_hit": 0, "both_miss": 0}
        for identity in common:
            label = labels_by_case[identity]
            if label["kind"] != "positive":
                continue
            l, r = (bool(_hits(outputs[identity][arm],label)) for arm in (lhs,rhs))
            wins[{(False, True):"gains", (True, False):"losses", (True, True):"both_hit",
                  (False, False):"both_miss"}[l,r]] += 1
        lost_abstentions = gained_abstentions = new_hard_errors = removed_hard_errors = 0
        for identity in common:
            label = labels_by_case[identity]["kind"]
            before, after = outputs[identity][lhs], outputs[identity][rhs]
            if label == "positive":
                lost_abstentions += before["status"] == "abstained" and after["status"] != "abstained"
                gained_abstentions += after["status"] == "abstained" and before["status"] != "abstained"
            elif label == "hard-negative":
                new_hard_errors += after["status"] == "selected" and before["status"] != "selected"
                removed_hard_errors += before["status"] == "selected" and after["status"] != "selected"
        paired[f"{rhs}_vs_{lhs}"] = {
            **wins, "positive_denominator": common_kind["positive"],
            "removed_false_abstentions": lost_abstentions, "new_false_abstentions": gained_abstentions,
            "new_hard_negative_false_positives": new_hard_errors,
            "removed_hard_negative_false_positives": removed_hard_errors,
            "hard_negative_denominator": common_kind["hard-negative"]
        }
    return {"contract": CONTRACT, "synthetic_only": True, "ranking_authorized": False,
            "study_acceptance": "not-evaluated", "total_cases": len(cohort), "common_case_ids": common,
            "overall_by_label": dict(Counter(labels_by_case[case]["kind"] for case in ordered_cases)),
            "excluded_from_common": excluded,
            "common_by_label": dict(common_kind), "common_minima_met": minimums,
            "violations": violations, "flow": {arm:dict(flow[arm]) for arm in ARMS},
            "missing_evidence": {arm:dict(missing_evidence[arm]) for arm in ARMS},
            "metrics_common": {a:_measure(common,a,outputs,labels_by_case,True) for a in ARMS},
            "metrics_available_only": {a:_measure(measured[a],a,outputs,labels_by_case,False) for a in ARMS},
            "paired_common": paired}
