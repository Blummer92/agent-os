"""Synthetic METADATA only; never reads an actual scenario or label."""
from copy import deepcopy
from hashlib import sha256
import json
import subprocess
import sys
from pathlib import Path
import unittest

from audit_intake import audit, utc, REPO, MINIMUM_FIELDS, read_meta_with_digest

BASE = Path(__file__).parent
REF = "https://github.com/Blummer92/agent-os/issues/1#issuecomment-1"
RUBRIC = BASE / "draft-rubric.json"
DIGEST = sha256(RUBRIC.read_bytes()).hexdigest()
DRAFT_RUBRIC_DATA = json.loads(RUBRIC.read_text())
RUBRIC_DATA = {**DRAFT_RUBRIC_DATA, "approval_state": "ratified"}

def rubric_bytes(rubric):
    return (json.dumps(rubric, sort_keys=True) + "\n").encode()

FIXTURE_DIGEST = sha256(rubric_bytes(RUBRIC_DATA)).hexdigest()
CUTOFF = "2026-11-19T00:00:00Z"
AS_OF = utc("2026-11-19T08:00:00Z")
AT = "2026-11-19T05:00:00Z"

def row(i):
    h = sha256(str(i).encode()).hexdigest()
    return dict(scenario_id=f"sc-{i}", family_hash=h, repository=REPO,
                pr_head_sha="a"*40, run_head_sha="a"*40, run_id=i, run_attempt=1,
                job_id=i, artifact_id=i, artifact_sha256=h, test_nodeid_sha256=h, occurred_at=AT)

def staged():
    d = json.loads((BASE/"draft-intake.json").read_text())
    d["stage"] = "frozen"
    d["configuration"].update(rubric_sha256=FIXTURE_DIGEST, recipe_sha256="f"*64)
    d["roles"].update(implementer="impl", registry_author_r1="author", independent_labeller_r2="labeller", split_custodian="custodian", trusted_observation_issuer="issuer", scorer="scorer")
    d["owner_approval"].update(ref=REF, approved_at=CUTOFF, scope="offline-shadow-only",
                              approved_vocabulary_sha256="b"*64, approved_rubric_sha256=FIXTURE_DIGEST,
                              approved_recipe_sha256="f"*64)
    d["registry_freeze"].update(git_sha="a"*40, sha256="d"*64, reviewed_identity_count=20, frozen_at=CUTOFF,
                                author_attestation_no_holdout_access_ref=REF,
                                custodian_revision_cutoff_attestation_ref=REF,
                                reviewed_revisions_after_cutoff_count=0)
    d["splits"].update(development=[row(1)], holdout=[row(i) for i in range(2,26)],
                       no_reuse_attestation_ref=REF, frozen_at=AT)
    d["labels"].update(sealed_gold_sha256="a"*64, custodian_counts_attestation_ref=REF,
                       label_count=24, positive_count=8, hard_negative_count=8)
    return d

class MetadataPrelude(unittest.TestCase):
    def result(self, d):
        return audit(d, RUBRIC_DATA, FIXTURE_DIGEST, AS_OF)
    def test_draft_is_blocked(self):
        out=self.result(json.loads((BASE/"draft-intake.json").read_text()))
        self.assertEqual(out["verdict"],"BLOCKED")
        self.assertEqual(out["ci_arms"],"BLOCKED_NO_VERIFIED_INPUT_METADATA")
        self.assertFalse(out["activation_authorized"])
    def test_valid_metadata_cannot_prove_evaluation_or_authorize(self):
        d=staged()
        obs=d["ci_observations"]
        obs.update(source_manifest_sha256="c"*64,custodian_authentication_ref=REF,mapping_recipe_sha256="e"*64)
        out=self.result(d)
        self.assertEqual(out["verdict"],"METADATA_PREFLIGHT_PASS_ONLY")
        self.assertEqual(out["ci_arms"],"UNVERIFIED_AUTHENTICATION_REQUIRED")
        self.assertFalse(out["activation_authorized"])
        self.assertFalse(out["label_content_inspected"])
    def test_split_overlap_is_detected_at_incident_family_level(self):
        d=staged()
        d["splits"]["holdout"][0]["family_hash"]=d["splits"]["development"][0]["family_hash"]
        self.assertIn("cross-split-overlap:incident-family",self.result(d)["blocking"])
    def test_wrong_head_or_extra_label_field_blocks(self):
        d = staged()
        d["splits"]["holdout"][0]["run_head_sha"]="b"*40
        d["splits"]["holdout"][1]["unexpected_payload"] = {}
        issues=self.result(d)["blocking"]
        self.assertIn("non-exact-head-or-invalid-receipt:holdout",issues)
        self.assertIn("non-metadata-or-malformed-split-row:holdout",issues)
    def test_role_case_collapse_and_early_reveal_are_blocked(self):
        d=staged()
        d["roles"]["independent_labeller_r2"]="AUTHOR"
        d["labels"]["unsealed_at"]=AT
        issues=self.result(d)["blocking"]
        self.assertIn("six-distinct-review-roles-required",issues)
        self.assertIn("gold-no-longer-sealed-before-this-intake-check",issues)


class D131Regression(unittest.TestCase):
    def result(self, d, rubric=None, as_of=AS_OF):
        if rubric is None: rubric = deepcopy(RUBRIC_DATA)
        digest = sha256(rubric_bytes(rubric)).hexdigest()
        d["configuration"]["rubric_sha256"] = digest
        d["owner_approval"]["approved_rubric_sha256"] = digest
        return audit(d, rubric, digest, as_of)

    def assert_metadata_pass(self, out):
        self.assertEqual(out["verdict"], "METADATA_PREFLIGHT_PASS_ONLY", out)
        self.assertFalse(out["activation_authorized"])
        self.assertFalse(out["label_content_inspected"])

    def test_all_four_raised_thresholds_are_independently_enforced(self):
        blockers = (
            "fewer-than-rubric-frozen-reviewed-identities",
            "fewer-than-rubric-heldout-scenarios",
            "fewer-than-rubric-positive-scenarios",
            "fewer-than-rubric-hard-negative-scenarios",
        )
        for name, blocker in zip(MINIMUM_FIELDS, blockers):
            with self.subTest(minimum=name):
                rubric = deepcopy(RUBRIC_DATA)
                rubric["cohort"][name] += 1
                out = self.result(staged(), rubric)
                self.assertEqual(out["verdict"], "BLOCKED")
                self.assertIn(blocker, out["blocking"])
                self.assertEqual(out["rubric_thresholds_validated"][name], rubric["cohort"][name])

    def test_positive_integral_rubric_minima_control_metadata_result(self):
        rubric = deepcopy(RUBRIC_DATA)
        for name, n in zip(MINIMUM_FIELDS, (2, 3, 1, 1)):
            rubric["cohort"][name] = n
        d = staged()
        d["registry_freeze"]["reviewed_identity_count"] = 2
        d["splits"]["holdout"] = d["splits"]["holdout"][:3]
        d["labels"].update(label_count=3, positive_count=1, hard_negative_count=1)
        self.assert_metadata_pass(self.result(d, rubric))

    def test_every_minimum_rejects_missing_and_malformed_values(self):
        for name in MINIMUM_FIELDS:
            cases = (None, False, True, 0, -1, 2.0, "20", [], {})
            for invalid in cases:
                with self.subTest(field=name, invalid=invalid):
                    rubric = deepcopy(RUBRIC_DATA)
                    rubric["cohort"][name] = invalid
                    out = self.result(staged(), rubric)
                    self.assertEqual(out["verdict"], "BLOCKED")
                    self.assertIn("missing-or-invalid-rubric-threshold:" + name, out["blocking"])
            with self.subTest(field=name, missing=True):
                rubric = deepcopy(RUBRIC_DATA)
                del rubric["cohort"][name]
                self.assertIn("missing-or-invalid-rubric-threshold:" + name,
                              self.result(staged(), rubric)["blocking"])

    def test_unsupported_rubric_schema_and_invalid_cutoff_block(self):
        rubric = deepcopy(RUBRIC_DATA)
        rubric["schema"] = "agent-os/ckr-pr3-rubric/draft-v999"
        self.assertIn("unsupported-rubric-schema", self.result(staged(), rubric)["blocking"])
        for invalid in (None, "2026-11-30", "2026-11-19T00:00:00.0000001Z", "2026-02-30T00:00:00Z"):
            with self.subTest(invalid_cutoff=invalid):
                rubric = deepcopy(RUBRIC_DATA)
                rubric["cohort"]["temporal_cutoff_utc"] = invalid
                self.assertIn("invalid-rubric-cutoff", self.result(staged(), rubric)["blocking"])

    def test_holdout_cutoff_is_inclusive_only_applied_to_holdout(self):
        d = staged()
        d["splits"]["development"][0]["occurred_at"] = "2026-11-18T23:59:59.999999Z"
        d["splits"]["holdout"][0]["occurred_at"] = CUTOFF
        self.assert_metadata_pass(self.result(d))
        d["splits"]["holdout"][0]["occurred_at"] = "2026-11-18T23:59:59.999999Z"
        out = self.result(d)
        self.assertEqual(out["verdict"], "BLOCKED")
        self.assertIn("holdout-predates-rubric-cutoff", out["blocking"])

    def test_both_splits_apply_inclusive_freeze_boundary(self):
        for name in ("development", "holdout"):
            with self.subTest(split=name):
                d = staged()  # All original occurrences exactly at freeze.
                self.assert_metadata_pass(self.result(d))
                d["splits"][name][0]["occurred_at"] = "2026-11-19T04:59:59.999999Z"
                self.assert_metadata_pass(self.result(d))
                d["splits"][name][0]["occurred_at"] = "2026-11-19T05:00:00.000001Z"
                out = self.result(d)
                self.assertEqual(out["verdict"], "BLOCKED")
                self.assertIn("scenario-occurred-after-split-freeze:" + name, out["blocking"])

    def test_sub_microsecond_precision_is_not_silently_truncated(self):
        d = staged()
        d["owner_approval"]["approved_at"] = "2026-11-19T05:00:00.0000001Z"
        self.assertIn("approval-and-freeze-chronology-unverified", self.result(d)["blocking"])
        d = staged()
        d["splits"]["holdout"][0]["occurred_at"] = "2026-11-19T05:00:00.0000001Z"
        self.assertIn("non-exact-head-or-invalid-receipt:holdout", self.result(d)["blocking"])

    def test_future_occurrences_block_independently_of_freeze_check(self):
        d = staged()
        # If freeze were the only upper bound, both this row and freeze equalling it could pass.
        future = "2026-11-19T08:00:00.000001Z"
        d["splits"]["frozen_at"] = future
        for name in ("development", "holdout"):
            d["splits"][name][0]["occurred_at"] = future
        out = self.result(d)
        self.assertEqual(out["verdict"], "BLOCKED")
        for name in ("development", "holdout"):
            self.assertIn("scenario-occurrence-in-future:" + name, out["blocking"])
            self.assertNotIn("scenario-occurred-after-split-freeze:" + name, out["blocking"])
        self.assertIn("future-intake-timestamp:split-freeze", out["blocking"])

    def test_clock_boundary_is_inclusive_and_future_approvals_and_registry_block(self):
        d = staged()
        self.assert_metadata_pass(self.result(d, as_of=utc(AT)))
        future = "2026-11-19T08:00:00.000001Z"
        d["owner_approval"]["approved_at"] = future
        d["registry_freeze"]["frozen_at"] = future
        out = self.result(d)
        self.assertIn("future-intake-timestamp:owner-approval", out["blocking"])
        self.assertIn("future-intake-timestamp:registry-freeze", out["blocking"])

    def test_cli_rejects_future_validation_clock_instead_of_overriding_wall_time(self):
        cp = subprocess.run([sys.executable, str(BASE/"audit_intake.py"), str(BASE/"draft-intake.json"),
            "--as-of", "9999-12-31T23:59:59Z"], capture_output=True, text=True, check=False)
        self.assertEqual(cp.returncode, 2)
        self.assertEqual(json.loads(cp.stdout)["blocking"], ["invalid-or-future-validation-clock"])

    def test_cli_rubric_digest_corresponds_to_same_bytes_it_parses(self):
        class OneShotRubric:
            calls = 0
            def open(self, mode):
                from io import BytesIO
                self.calls += 1
                assert self.calls == 1 and mode == "rb"
                return BytesIO(RUBRIC.read_bytes())
        source = OneShotRubric()
        parsed, digest = read_meta_with_digest(source)
        self.assertEqual((parsed, digest, source.calls), (DRAFT_RUBRIC_DATA, DIGEST, 1))


class ClaudeQARegression(unittest.TestCase):
    def result(self, d, rubric=RUBRIC_DATA):
        digest = sha256(rubric_bytes(rubric)).hexdigest()
        return audit(d, rubric, digest, AS_OF)

    def test_repeated_holdout_family_fails_uniqueness_and_minimum(self):
        d = staged()
        family = d["splits"]["holdout"][0]["family_hash"]
        for row in d["splits"]["holdout"]:
            row["family_hash"] = family
        out = self.result(d)
        self.assertEqual(out["valid_shape_rows"]["holdout"], 24)
        self.assertEqual(out["blocking"], ["duplicate-incident-family:holdout",
                                            "fewer-than-rubric-heldout-scenarios"])

    def test_shared_job_with_distinct_families_and_nodes_not_a_collision(self):
        d = staged()
        rows = d["splits"]["holdout"]
        for row in rows:
            for key in ("run_id", "run_attempt", "job_id", "artifact_id", "artifact_sha256"):
                row[key] = rows[0][key]
        self.assertEqual(self.result(d)["blocking"], [])

    def test_rehashed_small_rubric_cannot_reuse_prior_owner_digest(self):
        d = staged()
        rubric = deepcopy(RUBRIC_DATA)
        rubric["cohort"].update(zip(MINIMUM_FIELDS, (1, 2, 1, 1)))
        d["configuration"]["rubric_sha256"] = sha256(rubric_bytes(rubric)).hexdigest()
        d["registry_freeze"]["reviewed_identity_count"] = 1
        d["splits"]["holdout"] = d["splits"]["holdout"][:2]
        d["labels"].update(label_count=2, positive_count=1, hard_negative_count=1)
        self.assertEqual(self.result(d, rubric)["blocking"],
                         ["owner-approved-rubric-digest-not-bound"])

    def test_declared_proposed_rubric_and_stale_recipe_are_independent_blockers(self):
        d = staged()
        d["configuration"]["rubric_sha256"] = d["owner_approval"]["approved_rubric_sha256"] = (
            sha256(rubric_bytes(DRAFT_RUBRIC_DATA)).hexdigest())
        d["configuration"]["recipe_sha256"] = "c" * 64
        self.assertEqual(self.result(d, DRAFT_RUBRIC_DATA)["blocking"],
                         ["owner-approved-recipe-digest-not-bound", "rubric-not-declared-ratified"])

    def test_missing_and_case_alias_issuer_or_scorer_fail(self):
        for key in ("trusted_observation_issuer", "scorer"):
            for alias in (None, "LABELLER", "CUSTODIAN"):
                with self.subTest(role=key, alias=alias):
                    d = staged()
                    d["roles"][key] = alias
                    self.assertEqual(self.result(d)["blocking"], ["six-distinct-review-roles-required"])

    def test_registry_cutoff_is_inclusive_and_requires_a_zero_count_attestation(self):
        d = staged()
        self.assertEqual(self.result(d)["blocking"], [])
        d["registry_freeze"]["frozen_at"] = "2026-11-19T00:00:00.000001Z"
        self.assertEqual(self.result(d)["blocking"], ["registry-freeze-not-at-or-before-cutoff"])
        for bad_count in (None, False, 1, -1, "0"):
            with self.subTest(bad_count=bad_count):
                d = staged()
                d["registry_freeze"]["reviewed_revisions_after_cutoff_count"] = bad_count
                self.assertEqual(self.result(d)["blocking"], ["post-cutoff-revision-count-not-attested-zero"])
        d = staged()
        d["registry_freeze"]["custodian_revision_cutoff_attestation_ref"] = None
        self.assertEqual(self.result(d)["blocking"], ["custodian-revision-cutoff-attestation-missing"])

    def test_all_intake_objects_are_closed_and_blocker_does_not_echo_input(self):
        orig = staged()
        paths = ["root"] + [k for k, v in orig.items() if isinstance(v, dict)]
        for name in paths:
            with self.subTest(section=name):
                d = deepcopy(orig)
                (d if name == "root" else d[name])["unrecognized"] = "synthetic-payload"
                out = self.result(d)
                self.assertEqual(out["blocking"], ["unknown-intake-fields:" + name])
                self.assertNotIn("synthetic-payload", json.dumps(out))

    def test_deeply_nested_metadata_blocks_with_structured_exit_on_either_input(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            intake, rubric = Path(tmp) / "intake.json", Path(tmp) / "rubric.json"
            for input_path in (intake, rubric):
                with self.subTest(input=input_path.name):
                    intake.write_text(json.dumps(staged()))
                    rubric.write_bytes(rubric_bytes(RUBRIC_DATA))
                    input_path.write_text("[" * 20_000 + "]" * 20_000)
                    cp = subprocess.run([sys.executable, "-I", str(BASE/"audit_intake.py"),
                                         str(intake), "--rubric", str(rubric)],
                                        capture_output=True, text=True)
                    self.assertEqual(cp.returncode, 2)
                    self.assertEqual(cp.stderr, "")
                    self.assertEqual(json.loads(cp.stdout), {
                        "verdict": "BLOCKED", "blocking": ["RecursionError"],
                        "activation_authorized": False, "label_content_inspected": False})

    def test_positive_and_hard_negative_deficit_are_separately_identified(self):
        for label, kind in (("positive_count", "positive"), ("hard_negative_count", "hard-negative")):
            with self.subTest(label=label):
                d = staged()
                d["labels"][label] -= 1
                self.assertEqual(self.result(d)["blocking"], ["fewer-than-rubric-" + kind + "-scenarios"])

    def test_old_schema_and_unsealed_claim_remain_blocked(self):
        d = staged()
        d["schema"] = "agent-os/ckr-pr3-intake/v1"
        d["labels"]["unsealed_at"] = AT
        self.assertEqual(self.result(d)["blocking"], ["gold-no-longer-sealed-before-this-intake-check",
                                                      "unexpected-intake-schema"])

if __name__ == "__main__":
    unittest.main()
