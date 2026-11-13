"""LIVE10 campaign disposable fixture (AOS-CKR6-CI-LIVE10-20261113).

NEVER MERGE. Exists only on branch agent/ckr6-ci-live10-20261113 to give the
controlled CI test target (T09/T10) a minimal, reversible test. H2 (this head)
DELIBERATELY FAILS so hosted CI must reject it; H3 restores the passing form.
"""


def test_live10_campaign_fixture_control():
    assert False, "LIVE10-T09 deliberate failure: hosted CI must reject this head"
