from scripts.agent_os_execution_interface.continuation_driver import ContinuationDecision, drive_governed_continuation


class Adapter:
    def __init__(self): self.stage = 0; self.actions = []
    def observe(self): return self.stage
    def dispatch(self, action): self.actions.append(action); self.stage += 1


def test_multistage_mission_reaches_terminal_state_without_user_turns():
    adapter = Adapter()
    actions = ("implement", "test", "validate", "create-draft-pr")
    def decide(stage):
        return ContinuationDecision("", terminal=True) if stage == len(actions) else ContinuationDecision(actions[stage])
    result = drive_governed_continuation(adapter, decide)
    assert result.status == "completed"
    assert result.transitions == actions
    assert result.user_turns_required == 0


def test_genuine_boundary_stops_without_dispatch():
    adapter = Adapter()
    result = drive_governed_continuation(adapter, lambda _: ContinuationDecision("", blocked=True, reason_codes=("excluded-surface-authorization-required",)))
    assert result.status == "blocked"
    assert adapter.actions == []


def test_repeated_action_name_can_advance_across_new_observations():
    adapter = Adapter()
    def decide(stage):
        return ContinuationDecision("", terminal=True) if stage == 2 else ContinuationDecision("retry-validation")
    result = drive_governed_continuation(adapter, decide)
    assert result.status == "completed"
    assert result.transitions == ("retry-validation", "retry-validation")


def test_explicit_semantic_stall_stops_finitely():
    adapter = Adapter()
    result = drive_governed_continuation(adapter, lambda _: ContinuationDecision("retry-validation", stalled=True))
    assert result.status == "recovery-stalled"
    assert adapter.actions == []
