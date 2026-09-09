from dataclasses import dataclass


@dataclass(frozen=True)
class InvestigationDisposition:
    dod_satisfied: bool
    final_disposition_persisted: bool
    successor_required: bool
    successor_created: bool
    blocked: bool = False

    @property
    def investigation_complete(self) -> bool:
        return self.dod_satisfied and self.final_disposition_persisted and not self.blocked and (not self.successor_required or self.successor_created)


def test_completed_investigation_is_complete_even_when_implementation_moves_to_successor():
    state = InvestigationDisposition(True, True, True, True)
    assert state.investigation_complete is True


def test_missing_dod_or_blocked_disposition_does_not_complete_investigation():
    assert InvestigationDisposition(False, True, True, True).investigation_complete is False
    assert InvestigationDisposition(True, True, True, True, blocked=True).investigation_complete is False


def test_required_successor_must_exist_before_investigation_completion():
    assert InvestigationDisposition(True, True, True, False).investigation_complete is False
