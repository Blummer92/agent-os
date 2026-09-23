from notion_operational_guidance_writer.writer import *

SHA = "a" * 40
LINK = "https://github.com/Blummer92/agent-os/issues/1416"


def handoff(*, action="no implementation action; preserve terminal state", blocker=None, revision=SHA):
    return CodingCommandCenterHandoffEvidence("Blummer92/agent-os", 1416, revision, action, blocker, ())


def request(*, evidence=None, dry_run=False):
    return OperationalGuidanceWriteRequest(
        DATA_SOURCE_ID, LINK, "Source Link", "Blummer92/agent-os", 1416, SHA,
        evidence or handoff(),
        PropertyBinding("next_action", "Next Action", "text"),
        PropertyBinding("blocked_reason", "Blocked Reason", "text"),
        dry_run,
    )


class FakeClient:
    def __init__(self, page=None, pages=None, schema=None, bad_readback=False):
        self.page = page or NotionTaskPageEvidence("p1", LINK, "implement it", "old blocker")
        self.pages = pages
        self.schema = schema or (
            NotionPropertySpec("Source Link", "url"),
            NotionPropertySpec("Next Action", "text"),
            NotionPropertySpec("Blocked Reason", "text"),
        )
        self.bad_readback = bad_readback
        self.updates = []
    def fetch_schema(self, data_source_id): return self.schema
    def find_exact(self, **kwargs): return self.pages if self.pages is not None else (self.page,)
    def update_page(self, *, page_id, properties):
        self.updates.append((page_id, properties))
        values = dict(properties)
        self.page = NotionTaskPageEvidence(page_id, self.page.source_link, values.get("Next Action", self.page.next_action), values.get("Blocked Reason", self.page.blocked_reason))
    def fetch_page(self, page_id):
        if self.bad_readback: return NotionTaskPageEvidence(page_id, LINK, "wrong", "wrong")
        return self.page


def test_completed_issue_replaces_stale_implementation_guidance():
    client = FakeClient()
    result = plan_and_write_operational_guidance(request(), client)
    assert result.state is WriteState.UPDATED
    assert result.readback_verified
    assert client.updates == [("p1", (("Next Action", "no implementation action; preserve terminal state"), ("Blocked Reason", "")))]


def test_blocked_issue_preserves_canonical_blocker_code():
    evidence = handoff(action="clear the primary canonical blocker before continuing", blocker="dependency.blocked")
    client = FakeClient()
    result = plan_and_write_operational_guidance(request(evidence=evidence), client)
    assert result.state is WriteState.UPDATED
    assert result.intended_blocked_reason == "dependency.blocked"


def test_roadmap_next_action_is_consumed_not_invented():
    action = "continue with the canonical action for the current lifecycle stage"
    client = FakeClient()
    result = plan_and_write_operational_guidance(request(evidence=handoff(action=action)), client)
    assert result.intended_next_action == action


def test_unchanged_is_noop():
    page = NotionTaskPageEvidence("p1", LINK, "same", "dependency.blocked")
    client = FakeClient(page=page)
    result = plan_and_write_operational_guidance(request(evidence=handoff(action="same", blocker="dependency.blocked")), client)
    assert result.state is WriteState.UNCHANGED_SKIP
    assert result.readback_verified
    assert client.updates == []


def test_multiple_source_link_matches_fail_closed():
    page = NotionTaskPageEvidence("p1", LINK, "x", None)
    result = plan_and_write_operational_guidance(request(), FakeClient(pages=(page, NotionTaskPageEvidence("p2", LINK, "x", None))))
    assert result.state is WriteState.PRECHECK_FAILED
    assert "ambiguous" in result.reason_codes[0]


def test_schema_drift_fails_closed():
    client = FakeClient(schema=(NotionPropertySpec("Source Link", "url"), NotionPropertySpec("Next Action", "select"), NotionPropertySpec("Blocked Reason", "text")))
    assert plan_and_write_operational_guidance(request(), client).state is WriteState.PRECHECK_FAILED


def test_identity_disagreement_fails_closed():
    bad = CodingCommandCenterHandoffEvidence("other/repo", 1416, SHA, "x", None, ())
    assert plan_and_write_operational_guidance(request(evidence=bad), FakeClient()).state is WriteState.PRECHECK_FAILED


def test_stale_handoff_fails_closed():
    assert plan_and_write_operational_guidance(request(evidence=handoff(revision="b" * 40)), FakeClient()).state is WriteState.PRECHECK_FAILED


def test_readback_mismatch_fails_closed_without_retry():
    client = FakeClient(bad_readback=True)
    result = plan_and_write_operational_guidance(request(), client)
    assert result.state is WriteState.FAILED
    assert len(client.updates) == 1


def test_dry_run_makes_no_client_call():
    result = plan_and_write_operational_guidance(request(dry_run=True), None)
    assert result.state is WriteState.DRY_RUN
    assert not result.external_write_performed


def test_parser_consumes_exact_1097_fields():
    payload = {"schema_name": HANDOFF_SCHEMA_NAME, "schema_version": HANDOFF_SCHEMA_VERSION, "repository": "Blummer92/agent-os", "issue_number": 1416, "source_revision": SHA, "smallest_next_action": "x", "primary_blocker": None, "reason_codes": []}
    parsed = parse_coding_command_center_handoff(payload)
    assert parsed.smallest_next_action == "x"
    assert parsed.primary_blocker is None
