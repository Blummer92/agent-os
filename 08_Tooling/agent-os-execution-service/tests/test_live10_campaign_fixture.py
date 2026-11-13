"""LIVE10 campaign disposable fixture (AOS-CKR6-CI-LIVE10-20261113).

NEVER MERGE. Exists only on branch agent/ckr6-ci-live10-20261113 to give the
controlled CI test target (T09/T10) a minimal, reversible test. H1/H3 pass;
H2 deliberately fails to prove hosted CI rejects it.
"""


def test_live10_campaign_fixture_control():
    assert True
