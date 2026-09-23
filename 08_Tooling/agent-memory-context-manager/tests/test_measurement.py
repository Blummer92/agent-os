from agent_memory_context_manager.measurement import measured_reduction


def test_unavailable_before_is_not_imputed():
    assert measured_reduction(None, 1) is None


def test_unavailable_after_is_not_imputed():
    assert measured_reduction(1, None) is None


def test_zero_baseline_is_not_fractionally_comparable():
    assert measured_reduction(0, 0) is None


def test_equal_nonzero_values_report_zero_reduction():
    assert measured_reduction(10, 10) == 0.0


def test_measured_decrease_reports_positive_fractional_reduction():
    assert measured_reduction(10, 5) == 0.5


def test_measured_increase_reports_negative_fractional_reduction():
    assert measured_reduction(10, 15) == -0.5
