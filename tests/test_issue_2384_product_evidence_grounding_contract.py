def product_specific_claim_admissible(*, named_product: bool, current_evidence_present: bool) -> bool:
    if named_product and not current_evidence_present:
        return False
    return True


def test_named_product_practice_requires_current_product_evidence():
    assert product_specific_claim_admissible(named_product=True, current_evidence_present=False) is False


def test_named_product_practice_is_admissible_with_current_evidence():
    assert product_specific_claim_admissible(named_product=True, current_evidence_present=True) is True


def test_generic_design_practice_does_not_claim_product_grounding():
    assert product_specific_claim_admissible(named_product=False, current_evidence_present=False) is True
