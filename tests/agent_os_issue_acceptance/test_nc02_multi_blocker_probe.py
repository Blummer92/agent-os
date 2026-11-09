"""NC02 probe (Wave 3, DISPOSABLE — not a permanent test): stale-head must
survive alongside a second blocker.

Valid owner record + stale head + stale body. The receipt must name BOTH
blockers; dropping stale-head from the combined reasons is a
wrong-precedence defect even though the receipt stays blocked. The M1 test
(single blocker) cannot see this mutant — only this multi-blocker probe can.
"""
import test_merge_admission_actions as fixture


def test_nc02_stale_head_survives_second_blocker():
    owner_record = fixture.authorized_record()
    receipt = fixture.check_with_records(
        [owner_record],
        repo_kwargs={"head": "f" * 40, "body": "modified"},
    )
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert "stale-body" in receipt["reason_codes"]
    assert "stale-head" in receipt["reason_codes"]
