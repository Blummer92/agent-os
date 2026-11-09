"""Q04: owner-authored transport must not accept a non-owner authorization record."""
import test_merge_applicability as fixture


def test_q04_valid_owner_trigger_does_not_launder_foreign_authorizer(monkeypatch):
    # Keep the GitHub comment actor and transport owner-authored. Alter only
    # the canonical authorization producer's authorizer identity.
    owner_trigger = fixture._transport()
    monkeypatch.setattr(fixture, "OWNER", "mallory")
    foreign_record = fixture._authorized_record(None)
    monkeypatch.setattr(fixture, "OWNER", "Blummer92")
    receipt = fixture._run(record=foreign_record, transport=owner_trigger)
    assert receipt["dispatch_checks_passed"] is False
    assert receipt["merge_authorized"] is False
    assert "authorization.owner-provenance-mismatch" in receipt["reason_codes"]
