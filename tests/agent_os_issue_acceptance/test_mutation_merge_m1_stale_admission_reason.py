"""M1: distinguish stale head admission from later authorization blockers."""
import test_merge_admission_actions as fixture


def test_m1_stale_head_reason_survives_valid_owner_record():
    owner_record = fixture.authorized_record()
    receipt = fixture.check_with_records([owner_record], repo_kwargs={"head": "f" * 40})
    assert receipt["status"] == "blocked"
    assert receipt["merge_authorized"] is False
    assert "stale-head" in receipt["reason_codes"]
