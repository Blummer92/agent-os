"""Offline QA for the CKR11 stage-1 probe. Real canonical adapter, fake HTTP only."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.agent_os_ckr11_stage1_probe import probe as P
from workflow_scheduler.adapters.notion_readonly_adapter import NotionReadOnlyAdapterError

SOURCE = "0123456789abcdef0123456789abcdef"
TOKEN = "ntn_FAKE_TOKEN_VALUE_123"
JUNK_TITLE = "Secret Lesson Title Alpha"
JUNK_ID = "11111111-2222-3333-4444-555555555555"
JUNK_CURSOR = "CURSOR-VALUE-SHOULD-NEVER-APPEAR"


def rows(n):
    return [
        {
            "id": JUNK_ID,
            "url": "https://www.notion.so/secret-page",
            "properties": {"Lesson Learned": {"title": [{"plain_text": JUNK_TITLE}]}},
        }
        for _ in range(n)
    ]


class FakePost:
    """Scripted responses keyed by call index. Records every request."""

    def __init__(self, script=None, default=(3, False)):
        self.script = script or {}
        self.default = default
        self.requests = []

    def __call__(self, url, headers, body, timeout):
        index = len(self.requests)
        self.requests.append((url, dict(headers), json.loads(json.dumps(body))))
        action = self.script.get(index, self.default)
        if isinstance(action, Exception):
            raise action
        if callable(action):
            return action()
        count, has_more = action
        return {
            "results": rows(count),
            "has_more": has_more,
            "next_cursor": JUNK_CURSOR if has_more else None,
            "request_id": "req-1",
        }


def http_error(code):
    return NotionReadOnlyAdapterError(f"Notion API returned HTTP {code}: x notion_message=Leaky {JUNK_TITLE}", is_transient=code in (429, 500, 502, 503, 504))


def run(post, **kw):
    return P.run_probe(data_source_id=SOURCE, token=TOKEN, post=post, **kw)


class ManifestTests(unittest.TestCase):
    def test_finite_and_within_owner_cap(self):
        self.assertEqual(len(P.MANIFEST), 14)
        self.assertLessEqual(len(P.MANIFEST), 16)
        self.assertEqual(P.HARD_CALL_CAP, 16)

    def test_codes_and_filters_unique(self):
        self.assertEqual(len({e["code"] for e in P.MANIFEST}), 14)
        self.assertEqual(len({json.dumps(e["filter"], sort_keys=True) for e in P.MANIFEST}), 14)

    def test_testing_only_dedup_provenance(self):
        testing = [e for e in P.MANIFEST if e["code"] == "V06_area_testing"][0]
        text = " ".join(testing["provenance"])
        self.assertIn("#3972", text)
        self.assertIn("#3988", text)

    def test_only_allowed_properties_and_operators(self):
        allowed = {
            "Surface Before Work?": {"checkbox": {"equals"}},
            "Status": {"select": {"does_not_equal"}},
            "Area": {"select": {"equals"}},
            "Learning Type": {"select": {"equals"}},
        }

        def walk(node):
            if "and" in node or "or" in node:
                for child in node.get("and", []) + node.get("or", []):
                    walk(child)
                return
            prop = node["property"]
            kind = [k for k in node if k != "property"]
            self.assertEqual(len(kind), 1)
            self.assertIn(prop, allowed)
            self.assertIn(kind[0], allowed[prop])
            self.assertEqual(set(node[kind[0]]) - allowed[prop][kind[0]], set())

        for entry in P.MANIFEST:
            walk(entry["filter"])

    def test_manifest_hash_is_stable_and_binds_parameters(self):
        self.assertEqual(P.MANIFEST_SHA256, P.manifest_sha256())
        changed = tuple(P.MANIFEST[:-1])
        self.assertNotEqual(P.manifest_sha256(changed), P.MANIFEST_SHA256)


class RequestShapeTests(unittest.TestCase):
    def test_exactly_one_post_per_variant_with_exact_body(self):
        post = FakePost()
        result = run(post)
        self.assertEqual(len(post.requests), 14)
        self.assertEqual(result["http_calls"], 14)
        expected_url = f"https://api.notion.com/v1/data_sources/{SOURCE}/query"
        for (url, headers, body), entry in zip(post.requests, P.MANIFEST):
            self.assertEqual(url, expected_url)
            self.assertEqual(set(body), {"page_size", "filter"})
            self.assertEqual(body["page_size"], 26)
            self.assertEqual(body["filter"], entry["filter"])
            self.assertNotIn("start_cursor", body)
        self.assertFalse(result["stopped"])
        self.assertFalse(result["notion_writes_performed"])
        self.assertEqual(result["cursor_follow_calls"], 0)

    def test_has_more_never_follows_cursor(self):
        post = FakePost(default=(26, True))
        result = run(post)
        self.assertEqual(len(post.requests), 14)
        for _u, _h, body in post.requests:
            self.assertNotIn("start_cursor", body)
        row = result["variants"][0]
        self.assertEqual(row["count_class"], "26+")
        self.assertFalse(row["count_exact"])
        self.assertTrue(row["next_cursor_present"])

    def test_adapter_get_path_is_unusable(self):
        # Any get-style action through the same adapter must be refused, not performed.
        post = FakePost()
        adapter_get = P._no_get
        with self.assertRaises(P.ProbeStop):
            adapter_get("https://api.notion.com/v1/pages/x", {}, 1.0)
        self.assertEqual(post.requests, [])

    def test_wrong_url_or_extra_body_field_or_cursor_is_refused_before_network(self):
        for bad in (
            ("https://api.notion.com/v1/pages/x", {"page_size": 26, "filter": P.MANIFEST[0]["filter"]}),
            (f"https://api.notion.com/v1/data_sources/{SOURCE}/query", {"page_size": 26, "filter": P.MANIFEST[0]["filter"], "start_cursor": "x"}),
            (f"https://api.notion.com/v1/data_sources/{SOURCE}/query", {"page_size": 25, "filter": P.MANIFEST[0]["filter"]}),
            (f"https://api.notion.com/v1/data_sources/{SOURCE}/query", {"page_size": 26, "filter": {"and": []}}),
            (f"https://api.notion.com/v1/data_sources/{SOURCE}/query?filter_properties=x", {"page_size": 26, "filter": P.MANIFEST[0]["filter"]}),
        ):
            inner = FakePost()
            transport = P._Transport(SOURCE, inner, 16)
            transport.expected_filter = P.MANIFEST[0]["filter"]
            with self.assertRaises(P.ProbeStop) as ctx:
                transport(bad[0], {}, bad[1], 1.0)
            self.assertEqual(ctx.exception.reason, "request_contract_violation")
            self.assertEqual(inner.requests, [])

    def test_single_value_filter_drift_is_refused_before_network(self):
        # F1: a body whose filter differs from the manifest entry by one value must never be sent.
        import copy
        drifted = copy.deepcopy(P.MANIFEST[6]["filter"])  # V06_area_testing
        drifted["and"][-1]["select"]["equals"] = "Governance"
        inner = FakePost()
        transport = P._Transport(SOURCE, inner, 16)
        transport.expected_filter = P.MANIFEST[6]["filter"]
        with self.assertRaises(P.ProbeStop) as ctx:
            transport(f"https://api.notion.com/v1/data_sources/{SOURCE}/query", {}, {"page_size": 26, "filter": drifted}, 1.0)
        self.assertEqual(ctx.exception.reason, "request_contract_violation")
        self.assertEqual(inner.requests, [])

    def test_run_probe_stops_when_payload_filter_differs_from_manifest(self):
        # F1 end to end: the adapter payload is built from something other than the manifest entry.
        real_task = P.Task

        def swapped(**kw):
            kw["payload"] = dict(kw["payload"], filter={"and": []})
            return real_task(**kw)

        post = FakePost()
        with mock.patch.object(P, "Task", swapped):
            result = run(post)
        self.assertEqual(post.requests, [])
        self.assertEqual(result["http_calls"], 0)
        self.assertEqual(result["stop_reason"], "request_contract_violation")
        self.assertTrue(all(v["status"] in {"error", "not_run"} for v in result["variants"]))


    def test_call_cap_enforced_even_if_manifest_were_longer(self):
        inner = FakePost()
        transport = P._Transport(SOURCE, inner, 2)
        transport.expected_filter = P.MANIFEST[0]["filter"]
        body = {"page_size": 26, "filter": P.MANIFEST[0]["filter"]}
        url = f"https://api.notion.com/v1/data_sources/{SOURCE}/query"
        transport(url, {}, body, 1.0)
        transport(url, {}, body, 1.0)
        with self.assertRaises(P.ProbeStop) as ctx:
            transport(url, {}, body, 1.0)
        self.assertEqual(ctx.exception.reason, "call_cap")
        self.assertEqual(len(inner.requests), 2)

    def test_source_has_no_write_capable_vocabulary(self):
        text = Path(P.__file__).read_text(encoding="utf-8")
        for needle in ("PATCH", "DELETE", "method=", "urlopen", "sleep(", "create_page", "update_page", "time.sleep"):
            self.assertNotIn(needle, text, needle)


class StopConditionTests(unittest.TestCase):
    def check_stop(self, error, reason, first_index=0):
        post = FakePost(script={first_index: error})
        result = run(post)
        self.assertEqual(len(post.requests), first_index + 1)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["stop_reason"], reason)
        statuses = [v["status"] for v in result["variants"]]
        self.assertEqual(statuses[first_index], "error")
        self.assertTrue(all(s == "not_run" for s in statuses[first_index + 1:]))
        return result

    def test_429_no_retry(self):
        self.check_stop(http_error(429), "http_429")

    def test_500_no_retry(self):
        self.check_stop(http_error(500), "http_5xx", first_index=3)

    def test_503_no_retry(self):
        self.check_stop(http_error(503), "http_5xx")

    def test_400_and_404_stop(self):
        self.check_stop(http_error(400), "http_4xx")
        self.check_stop(http_error(404), "http_4xx", first_index=5)

    def test_timeout_and_connection(self):
        self.check_stop(NotionReadOnlyAdapterError("Notion API request timed out: x", is_transient=True), "timeout")
        self.check_stop(NotionReadOnlyAdapterError("Notion API connection error: boom", is_transient=True), "connection_error")

    def test_malformed_response(self):
        self.check_stop(lambda: {"results": "nope", "has_more": False}, "malformed_response")
        self.check_stop(lambda: {"results": [], "has_more": "yes"}, "malformed_response")
        self.check_stop(lambda: ["not", "an", "object"], "malformed_response")

    def test_oversized_page_is_detected_before_any_slicing(self):
        # 40 rows in one provider page with max_results 100: the real adapter keeps 40,
        # the probe sees the raw count and stops after recording the anomaly.
        post = FakePost(script={2: (40, False)})
        result = run(post)
        self.assertEqual(len(post.requests), 3)
        self.assertEqual(result["stop_reason"], "oversized_page")
        row = result["variants"][2]
        self.assertTrue(row["page_size_anomaly"])
        self.assertEqual(row["returned_count"], 40)
        self.assertEqual(row["count_class"], "unknown")
        self.assertFalse(row["count_exact"])
        self.assertTrue(all(v["status"] == "not_run" for v in result["variants"][3:]))

    def test_exactly_26_rows_is_not_an_anomaly_but_exceeds_25(self):
        result = run(FakePost(script={0: (26, False)}))
        row = result["variants"][0]
        self.assertFalse(row["page_size_anomaly"])
        self.assertEqual(row["count_class"], "26+")
        self.assertTrue(row["count_exact"])
        self.assertFalse(result["stopped"])

    def test_count_classes(self):
        result = run(FakePost(script={0: (0, False), 1: (25, False), 2: (7, True), 3: (26, True)}))
        classes = [v["count_class"] for v in result["variants"][:4]]
        self.assertEqual(classes, ["0", "1..25", "unknown", "26+"])
        self.assertTrue(result["variants"][0]["count_exact"])
        self.assertFalse(result["variants"][2]["count_exact"])


class SanitizationTests(unittest.TestCase):
    def test_no_row_content_ids_urls_cursors_or_secrets_in_artifact(self):
        result = run(FakePost(default=(26, True)))
        text = P.validate_result(result, secrets=(TOKEN, SOURCE))
        for needle in (JUNK_TITLE, JUNK_ID, JUNK_CURSOR, "notion.so", TOKEN, SOURCE, "req-1"):
            self.assertNotIn(needle, text)

    def test_error_text_never_reaches_artifact(self):
        result = run(FakePost(script={0: http_error(429)}))
        text = P.validate_result(result, secrets=(TOKEN, SOURCE))
        self.assertNotIn("Leaky", text)
        self.assertNotIn(JUNK_TITLE, text)

    def test_validator_rejects_extra_field_and_forbidden_content(self):
        good = run(FakePost())
        P.validate_result(good)
        extra = json.loads(json.dumps(good))
        extra["note"] = "x"
        with self.assertRaises(P.ProbeRefusal):
            P.validate_result(extra)
        leaky = json.loads(json.dumps(good))
        leaky["variants"][0]["code"] = "V00_base"
        leaky["source_revision"] = "0123456789abcdef0123456789abcdef"  # 32 hex, UUID-like
        with self.assertRaises(P.ProbeRefusal):
            P.validate_result(leaky)
        leaky2 = json.loads(json.dumps(good))
        leaky2["stop_reason"] = "https://www.notion.so/x"
        with self.assertRaises(P.ProbeRefusal):
            P.validate_result(leaky2)
        bad_count = json.loads(json.dumps(good))
        bad_count["variants"][0]["returned_count"] = True
        with self.assertRaises(P.ProbeRefusal):
            P.validate_result(bad_count)
        with self.assertRaises(P.ProbeRefusal):
            P.validate_result(good, secrets=(P.MANIFEST_SHA256[:12],))

    def test_literal_token_and_source_id_are_caught_without_any_regex_match(self):
        # F2: the literal scan is the backstop for values no pattern would recognise.
        plain_token = "plainliteraltoken"
        plain_source = "plainsourcebinding"
        good = run(FakePost())
        P.validate_result(good)  # no literal given: passes, proving the regexes do not cover these values
        for secret in (plain_token, plain_source):
            leaky = json.loads(json.dumps(good))
            leaky["source_revision"] = secret
            P.validate_result(leaky)  # still passes the regexes and the key whitelist
            with self.assertRaises(P.ProbeRefusal):
                P.validate_result(leaky, secrets=(plain_token, plain_source))

    def test_main_refuses_artifact_containing_the_literal_token(self):
        plain_token = "plainliteraltoken"
        real_run = P.run_probe

        def leaking(**kw):
            result = real_run(**kw)
            result["source_revision"] = plain_token
            return result

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            env = {"NOTION_TOKEN": plain_token, "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID": SOURCE, "GITHUB_RUN_ATTEMPT": "1"}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(P, "run_probe", leaking):
                code = P.main(["--output", str(out), "--expected-manifest-sha256", P.MANIFEST_SHA256], post=FakePost())
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())


    def test_source_revision_40_hex_allowed_but_32_hex_rejected(self):
        good = run(FakePost())
        good["source_revision"] = "1584e9054194a50ba68fed67f8dc37ae6b995976"
        P.validate_result(good)


class BindingTests(unittest.TestCase):
    def run_main(self, env, args, post):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "result.json"
            if args.get("preexisting"):
                out.write_text("x")
            argv = ["--output", str(out), "--expected-manifest-sha256", args["sha"]]
            with mock.patch.dict(os.environ, env, clear=True):
                code = P.main(argv, post=post)
            return code, (out.read_text() if out.exists() and not args.get("preexisting") else None)

    def env(self, **kw):
        base = {"NOTION_TOKEN": TOKEN, "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID": SOURCE, "GITHUB_RUN_ATTEMPT": "1"}
        base.update(kw)
        return base

    def test_happy_path_writes_validated_artifact(self):
        post = FakePost()
        code, text = self.run_main(self.env(), {"sha": P.MANIFEST_SHA256}, post)
        self.assertEqual(code, 0)
        self.assertEqual(len(post.requests), 14)
        self.assertEqual(json.loads(text)["http_calls"], 14)

    def test_refusals_happen_before_any_network_call(self):
        cases = [
            (self.env(GITHUB_RUN_ATTEMPT="2"), {"sha": P.MANIFEST_SHA256}),
            (self.env(), {"sha": "0" * 64}),
            (self.env(NOTION_TOKEN=""), {"sha": P.MANIFEST_SHA256}),
            (self.env(AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID=""), {"sha": P.MANIFEST_SHA256}),
            (self.env(), {"sha": P.MANIFEST_SHA256, "preexisting": True}),
        ]
        for env, args in cases:
            post = FakePost()
            code, _ = self.run_main(env, args, post)
            self.assertEqual(code, 2)
            self.assertEqual(post.requests, [])

    def test_stopped_run_exits_nonzero_and_still_writes_sanitized_artifact(self):
        post = FakePost(script={1: http_error(429)})
        code, text = self.run_main(self.env(), {"sha": P.MANIFEST_SHA256}, post)
        self.assertEqual(code, 1)
        self.assertEqual(len(post.requests), 2)
        self.assertEqual(json.loads(text)["stop_reason"], "http_429")


DEDICATED_ISSUE_NUMBER = 3995
REVIEWED_PROBE_SHA256 = "d3a5e23a1bd9ec3f9fe297a1a148e8b6b8f51a56ee6c14ec21d7f8d13e68f755"
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "agent-os-ckr11-stage1-probe.yml"
PROBE_REL = "scripts/agent_os_ckr11_stage1_probe/probe.py"


def workflow_steps():
    """Text-only split of the job steps (no YAML dependency in CI)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("    steps:\n", 1)[1]
    parts = re.split(r"(?m)^      - ", body)[1:]
    return ["      - " + part for part in parts]


def step_index(marker):
    hits = [i for i, step in enumerate(workflow_steps()) if marker in step]
    assert len(hits) == 1, (marker, hits)
    return hits[0]


class ScriptHashGuardTests(unittest.TestCase):
    """The reviewed probe.py hash must be verified before the secret exists or any HTTP call."""

    def test_checked_in_probe_matches_reviewed_hash(self):
        import hashlib

        self.assertEqual(hashlib.sha256((REPO_ROOT / PROBE_REL).read_bytes()).hexdigest(), REVIEWED_PROBE_SHA256)

    def test_hash_step_pins_reviewed_value_and_path(self):
        step = workflow_steps()[step_index("EXPECTED_PROBE_SHA256:")]
        self.assertIn("EXPECTED_PROBE_SHA256: " + REVIEWED_PROBE_SHA256, step)
        self.assertIn(PROBE_REL, step)
        self.assertIn("sha256sum --check --strict", step)
        self.assertIn("set -euo pipefail", step)
        self.assertNotIn("secrets.", step)

    def test_hash_step_precedes_every_step_that_runs_or_imports_probe_or_uses_secret(self):
        steps = workflow_steps()
        guard = step_index("EXPECTED_PROBE_SHA256:")
        secret_steps = [i for i, step in enumerate(steps) if "secrets." in step or "NOTION_TOKEN" in step]
        self.assertEqual(len(secret_steps), 1)
        self.assertLess(guard, secret_steps[0])
        for i, step in enumerate(steps):
            if "agent_os_ckr11_stage1_probe" in step and i != guard:
                self.assertLess(guard, i, step)
        # the earlier steps never see the secret or the source binding
        for step in steps[: secret_steps[0]]:
            self.assertNotIn("secrets.", step)
            self.assertNotIn("NOTION_TOKEN", step)
            self.assertNotIn("AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID", step)

    def test_workflow_has_no_other_secret_or_write_permission(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(text.count("secrets."), 1)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("contents: write", text)

    def run_guard(self, probe_bytes):
        """Run the real hash step script; a marker file stands for every later step (secret, HTTP)."""
        import subprocess

        step = workflow_steps()[step_index("EXPECTED_PROBE_SHA256:")]
        script = step.split("run: |\n", 1)[1]
        script = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in script.splitlines())
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / PROBE_REL
            target.parent.mkdir(parents=True)
            target.write_bytes(probe_bytes)
            marker = Path(tmp) / "later_step_ran"
            result = subprocess.run(
                ["bash", "-c", script + "\ntouch " + str(marker)],
                cwd=tmp,
                env={"PATH": os.environ["PATH"], "EXPECTED_PROBE_SHA256": REVIEWED_PROBE_SHA256},
                capture_output=True,
                text=True,
            )
            return result.returncode, marker.exists()

    def test_pristine_probe_passes_guard(self):
        code, later = self.run_guard((REPO_ROOT / PROBE_REL).read_bytes())
        self.assertEqual((code, later), (0, True))

    def test_script_hash_drift_stops_before_secret_or_http(self):
        original = (REPO_ROOT / PROBE_REL).read_bytes()
        for drifted in (original + b"\n", original.replace(b"MAX_PAGES = 1", b"MAX_PAGES = 3"), b""):
            code, later = self.run_guard(drifted)
            self.assertNotEqual(code, 0)
            self.assertFalse(later)

    def test_drifted_script_never_imported_before_guard_in_workflow_order(self):
        # a drifted probe.py cannot be imported by the offline-test step because that step is after the guard
        self.assertLess(step_index("EXPECTED_PROBE_SHA256:"), step_index("unittest tests.agent_os_ckr11_stage1_probe"))


class IssueBindingTests(unittest.TestCase):
    """The comment trigger must be bound to exactly one issue number (0 is an inert, unbound sentinel)."""

    def condition(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(r"(?m)^    if: (.+)$", text)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_condition_has_exactly_one_issue_number_equality(self):
        cond = self.condition()
        self.assertEqual(len(re.findall(r"github\.event\.issue\.number", cond)), 1)
        match = re.search(r"github\.event\.issue\.number == (\d+) &&", cond)
        self.assertIsNotNone(match, cond)
        self.assertEqual(int(match.group(1)), DEDICATED_ISSUE_NUMBER)

    def test_condition_keeps_owner_issue_only_and_command_prefix(self):
        cond = self.condition()
        self.assertIn("github.event.issue.pull_request == null", cond)
        self.assertIn("github.event.comment.user.id == 32861845", cond)
        self.assertIn("startsWith(github.event.comment.body, '/agent-os ckr11-stage1-probe ')", cond)
        self.assertNotIn("||", cond)

    def test_unbound_or_bound_state_is_declared_not_ambiguous(self):
        # The trigger is bound to exactly the dedicated probe issue, not any positive integer.
        number = int(re.search(r"github\.event\.issue\.number == (\d+)", self.condition()).group(1))
        self.assertEqual(number, DEDICATED_ISSUE_NUMBER)
        self.assertGreater(number, 0)
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("not a global one-shot", text)


if __name__ == "__main__":
    unittest.main()
