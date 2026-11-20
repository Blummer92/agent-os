#!/usr/bin/env python3
"""Pre-score PR-3 metadata audit. Does not load labels, lesson text or CI contents."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

PIN = "07f9e0657d6fd8f5e3e2734e926856ded5111147"
REGISTRY_BLOB = "2fdcaba19a384e3c4e6217cbb81b600289ebe6d2"
REPO = "Blummer92/agent-os"
SHA40 = r"[0-9a-f]{40}"
SHA64 = r"[0-9a-f]{64}"
INTAKE_SCHEMA = "agent-os/ckr-pr3-intake/v2"
RUBRIC_SCHEMA = "agent-os/ckr-pr3-rubric/draft-v1"
MINIMUM_FIELDS = (
    "min_frozen_reviewed_lesson_identities", "min_holdout_scenarios",
    "min_positive_scenarios", "min_hard_negative_scenarios",
)
SPLIT_KEYS = {
    "scenario_id", "family_hash", "repository", "pr_head_sha", "run_head_sha",
    "run_id", "run_attempt", "job_id", "artifact_id", "artifact_sha256",
    "test_nodeid_sha256", "occurred_at",
}

ROLE_KEYS = (
    "implementer", "registry_author_r1", "independent_labeller_r2",
    "split_custodian", "trusted_observation_issuer", "scorer",
)
SECTION_KEYS = {
    "configuration": {"production_pin", "production_registry_git_blob_sha1",
                      "exact_repository", "rubric_sha256", "recipe_sha256"},
    "roles": set(ROLE_KEYS),
    "owner_approval": {"ref", "approved_at", "scope", "approved_vocabulary_sha256",
                       "approved_rubric_sha256", "approved_recipe_sha256"},
    "registry_freeze": {"git_sha", "sha256", "reviewed_identity_count", "frozen_at",
                        "author_attestation_no_holdout_access_ref",
                        "custodian_revision_cutoff_attestation_ref",
                        "reviewed_revisions_after_cutoff_count"},
    "splits": {"development", "holdout", "no_reuse_attestation_ref", "frozen_at"},
    "labels": {"sealed_gold_sha256", "custodian_counts_attestation_ref", "label_count",
               "positive_count", "hard_negative_count", "unsealed_at"},
    "ci_observations": {"source_manifest_sha256", "custodian_authentication_ref",
                        "mapping_recipe_sha256"},
}
TOP_KEYS = {"schema", "stage", "production_activation", *SECTION_KEYS}

def exact(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None

def utc(value):
    if not exact(value, r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z"):
        return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None

def read_meta_with_digest(path):
    def unique_pairs(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError("duplicate JSON member")
            d[k] = v
        return d
    with path.open("rb") as f:
        data = f.read(1_048_577)
    if len(data) > 1_048_576: raise ValueError("metadata size cap exceeded")
    return json.loads(data, object_pairs_hook=unique_pairs), hashlib.sha256(data).hexdigest()

def posint(value):
    return type(value) is int and value > 0

def is_receipt(value):
    # Only check presence/shape; a custodian must authenticate resolution and author.
    return exact(value, r"https://github\.com/Blummer92/agent-os/(?:issues|pull)/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*|#pullrequestreview-[1-9][0-9]*)")

def audit(intake, rubric, rubric_digest, as_of):
    issues = []
    def require(value, name):
        if not value: issues.append(name)
    def section(name):
        obj = intake.get(name)
        if type(obj) is not dict:
            issues.append("missing-or-invalid-section:" + name)
            return {}
        require(obj.keys() <= SECTION_KEYS[name], "unknown-intake-fields:" + name)
        return obj
    if type(intake) is not dict:
        return {"verdict": "BLOCKED", "blocking": ["invalid-intake"],
                "label_content_inspected": False, "activation_authorized": False}
    require(intake.keys() <= TOP_KEYS, "unknown-intake-fields:root")
    # A claimed ratification and matching digests are metadata, not authentication.
    require(type(rubric) is dict and rubric.get("schema") == RUBRIC_SCHEMA,
            "unsupported-rubric-schema")
    require(type(rubric) is dict and rubric.get("approval_state") == "ratified",
            "rubric-not-declared-ratified")
    cohort = rubric.get("cohort") if type(rubric) is dict else None
    if type(cohort) is not dict:
        issues.append("missing-or-invalid-rubric-cohort")
        cohort = {}
    limits = {}
    for field in MINIMUM_FIELDS:
        value = cohort.get(field)
        require(posint(value), "missing-or-invalid-rubric-threshold:" + field)
        if posint(value):
            limits[field] = value
    cutoff = utc(cohort.get("temporal_cutoff_utc"))
    require(cutoff is not None, "invalid-rubric-cutoff")
    if not isinstance(as_of, datetime) or as_of.tzinfo != timezone.utc:
        return {"verdict": "BLOCKED", "blocking": ["invalid-validation-clock"],
                "label_content_inspected": False, "activation_authorized": False}
    clock = as_of.isoformat().replace("+00:00", "Z")
    cfg = section("configuration")
    require(intake.get("schema") == INTAKE_SCHEMA, "unexpected-intake-schema")
    require(intake.get("stage") == "frozen", "intake-not-frozen")
    require(intake.get("production_activation") is False, "production-must-remain-inactive")
    require(cfg.get("production_pin") == PIN, "wrong-production-pin")
    require(cfg.get("production_registry_git_blob_sha1") == REGISTRY_BLOB, "wrong-production-registry")
    require(cfg.get("exact_repository") == REPO, "wrong-repository")
    require(cfg.get("rubric_sha256") == rubric_digest, "draft-rubric-digest-not-bound")
    require(exact(cfg.get("recipe_sha256"), SHA64), "ranking-and-scoring-recipe-not-frozen")
    roles = section("roles")
    ok_roles = all(exact(roles.get(k), r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})") for k in ROLE_KEYS)
    require(ok_roles and len({roles[k].casefold() for k in ROLE_KEYS}) == len(ROLE_KEYS),
            "six-distinct-review-roles-required")
    owner = section("owner_approval")
    require(is_receipt(owner.get("ref")), "owner-scope-approval-receipt-missing")
    require(owner.get("scope") == "offline-shadow-only", "owner-scope-not-shadow-only")
    require(exact(owner.get("approved_vocabulary_sha256"), SHA64), "owner-approved-vocabulary-digest-missing")
    require(exact(rubric_digest, SHA64) and owner.get("approved_rubric_sha256") == rubric_digest,
            "owner-approved-rubric-digest-not-bound")
    recipe_digest = cfg.get("recipe_sha256")
    require(exact(recipe_digest, SHA64) and owner.get("approved_recipe_sha256") == recipe_digest,
            "owner-approved-recipe-digest-not-bound")
    reg = section("registry_freeze")
    require(exact(reg.get("git_sha"), SHA40) and exact(reg.get("sha256"), SHA64), "r1-registry-sha-freeze-missing")
    min_reviewed = limits.get("min_frozen_reviewed_lesson_identities")
    require(posint(reg.get("reviewed_identity_count")) and min_reviewed is not None
            and reg["reviewed_identity_count"] >= min_reviewed,
            "fewer-than-rubric-frozen-reviewed-identities")
    require(is_receipt(reg.get("author_attestation_no_holdout_access_ref")), "r1-blinding-attestation-missing")
    registry_freeze = utc(reg.get("frozen_at"))
    require(registry_freeze is not None and cutoff is not None and registry_freeze <= cutoff,
            "registry-freeze-not-at-or-before-cutoff")
    require(is_receipt(reg.get("custodian_revision_cutoff_attestation_ref")),
            "custodian-revision-cutoff-attestation-missing")
    post_cutoff = reg.get("reviewed_revisions_after_cutoff_count")
    require(type(post_cutoff) is int and post_cutoff == 0,
            "post-cutoff-revision-count-not-attested-zero")
    split = section("splits")
    require(is_receipt(split.get("no_reuse_attestation_ref")), "custodian-split-group-no-reuse-attestation-missing")
    freeze = utc(split.get("frozen_at"))
    rows_by_split = {}
    for name in ("development", "holdout"):
        raw = split.get(name)
        if type(raw) is not list:
            issues.append("sealed-or-missing-disjoint-split-metadata:" + name)
            raw = []
        seen = set()
        for r in raw:
            if type(r) is not dict or set(r) != SPLIT_KEYS:
                issues.append("non-metadata-or-malformed-split-row:" + name)
                continue
            sha = r["pr_head_sha"]
            key = (r["run_id"], r["run_attempt"], r["job_id"], r["artifact_id"], r["test_nodeid_sha256"])
            label = r["scenario_id"]
            shape = (r["repository"] == REPO and exact(label, r"sc-[a-zA-Z0-9_-]{1,64}")
                     and exact(r["family_hash"], SHA64) and exact(sha, SHA40)
                     and r["run_head_sha"] == sha and all(posint(x) for x in key[:4])
                     and exact(key[4], SHA64) and exact(r["artifact_sha256"], SHA64) and utc(r["occurred_at"]))
            if not shape:
                issues.append("non-exact-head-or-invalid-receipt:" + name)
                continue
            if key in seen or label in seen:
                issues.append("duplicate-split-identity:" + name)
                continue
            seen.update((label, key))
            occurred_at = utc(r["occurred_at"])
            if name == "holdout" and cutoff is not None and occurred_at < cutoff:
                issues.append("holdout-predates-rubric-cutoff")
            if freeze is not None and occurred_at > freeze:
                issues.append("scenario-occurred-after-split-freeze:" + name)
            if occurred_at > as_of:
                issues.append("scenario-occurrence-in-future:" + name)
            rows_by_split.setdefault(name, []).append((label, key, r["family_hash"]))
    dev = rows_by_split.get("development", [])
    hold = rows_by_split.get("holdout", [])
    require(bool(dev), "development-split-empty")
    min_hold = limits.get("min_holdout_scenarios")
    holdout_family_count = len({r[2] for r in hold})
    require(holdout_family_count == len(hold), "duplicate-incident-family:holdout")
    require(min_hold is not None and holdout_family_count >= min_hold,
            "fewer-than-rubric-heldout-scenarios")
    for i, kind in enumerate(("scenario-id", "test-run-receipt", "incident-family")):
        require(not ({r[i] for r in dev} & {r[i] for r in hold}), "cross-split-overlap:" + kind)
    labels = section("labels")
    require(exact(labels.get("sealed_gold_sha256"), SHA64), "sealed-gold-digest-missing")
    require(is_receipt(labels.get("custodian_counts_attestation_ref")), "independent-gold-count-attestation-missing")
    counts = tuple(labels.get(k) for k in ("label_count", "positive_count", "hard_negative_count"))
    min_pos = limits.get("min_positive_scenarios")
    min_neg = limits.get("min_hard_negative_scenarios")
    require(all(type(x) is int and x >= 0 for x in counts)
            and counts[0] == len(hold) and sum(counts[1:]) <= counts[0],
            "gold-attested-counts-missing-or-inconsistent")
    require(min_pos is not None and posint(counts[1]) and counts[1] >= min_pos,
            "fewer-than-rubric-positive-scenarios")
    require(min_neg is not None and posint(counts[2]) and counts[2] >= min_neg,
            "fewer-than-rubric-hard-negative-scenarios")
    chronology = [utc(o.get(k)) for o,k in ((owner,"approved_at"), (reg,"frozen_at"), (split,"frozen_at"))]
    require(all(chronology) and chronology[0] <= min(chronology[1:]), "approval-and-freeze-chronology-unverified")
    for name, stamp in zip(("owner-approval", "registry-freeze", "split-freeze"), chronology):
        if stamp is not None and stamp > as_of:
            issues.append("future-intake-timestamp:" + name)
    if labels.get("unsealed_at") is not None:
        issues.append("gold-no-longer-sealed-before-this-intake-check")
    obs = section("ci_observations")
    ci_received = (exact(obs.get("source_manifest_sha256"), SHA64)
                   and exact(obs.get("mapping_recipe_sha256"), SHA64)
                   and is_receipt(obs.get("custodian_authentication_ref")))
    # Neither shape nor an attested hash grants authority; never issue a go/no-go.
    return {
        "verdict": "BLOCKED" if issues else "METADATA_PREFLIGHT_PASS_ONLY",
        "blocking": sorted(set(issues)), "label_content_inspected": False, "activation_authorized": False,
        "validation_as_of_utc": clock, "rubric_thresholds_validated": limits,
        "valid_shape_rows": {"development": len(dev), "holdout": len(hold)},
        "ci_observation_metadata_received": bool(ci_received),
        "ci_arms": "UNVERIFIED_AUTHENTICATION_REQUIRED" if ci_received else "BLOCKED_NO_VERIFIED_INPUT_METADATA",
        "manual_checks": [
            "Authenticate the owner receipt and exact rubric and recipe digests, all role identities, and custodian attestations independently.",
            "Verify incident-family lineage and the frozen snapshot and revision timestamps; hashes and counts are claims only.",
            "Verify pinned registry SHA, recent revision bindings and vocabulary against exact source through the existing validator.",
            "Verify artifact/run/job provenance and authentic observation construction independently; these are metadata claims.",
            "Freeze prediction outputs before gold unsealing; the metadata auditor never reads labels or evaluates recommendations."
        ]
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("intake", type=Path)
    p.add_argument("--rubric", type=Path, default=Path(__file__).with_name("draft-rubric.json"))
    p.add_argument("--as-of", help="UTC replay clock, no later than current UTC time")
    a=p.parse_args()
    now = datetime.now(timezone.utc)
    as_of = utc(a.as_of) if a.as_of is not None else now
    try:
        if as_of is None or as_of > now:
            result = {"verdict": "BLOCKED", "blocking": ["invalid-or-future-validation-clock"],
                      "label_content_inspected": False, "activation_authorized": False}
        else:
            rubric, digest = read_meta_with_digest(a.rubric)
            intake, _ = read_meta_with_digest(a.intake)
            result = audit(intake, rubric, digest, as_of)
    except (OSError, TypeError, ValueError, KeyError, RecursionError) as e:
        result = {"verdict": "BLOCKED", "blocking": [type(e).__name__],
                  "label_content_inspected": False, "activation_authorized": False}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "METADATA_PREFLIGHT_PASS_ONLY" else 2

if __name__ == "__main__":
    raise SystemExit(main())
