# Work Scanner grading contracts

This package owns platform-neutral Work Scanner grading evidence and decision contracts.

## WS-GRADE1 boundary

`grading_decision.py` defines the portable grading decision produced after grading evidence has been evaluated. It deliberately contains no Schoology, PowerSchool, browser, selector, URL, cookie, token, session, DOM, login, or write-execution details.

The contract binds:

- resolved student identity evidence;
- resolved assignment identity evidence;
- rubric criteria and supporting evidence;
- proposed score and maximum score;
- feedback;
- confidence and explicit uncertainty reasons;
- teacher approval state;
- evidence freshness;
- source provenance and content digests;
- caller-requested target platforms; and
- a deterministic `grading-decision:<sha256>` identity over canonical serialized content.

## Authority separation

A grading decision is **not write authority**. `write_authorized` is permanently false in this contract. `eligible_for_authorization_review` means only that the decision has resolved identities, current evidence, explicit teacher approval, and no recorded uncertainty. A later separately governed authorization contract must still approve the exact mutation before any platform writer can act.

Platform adapters may consume the same decision identity, but they may not change grading semantics or manufacture approval. Ambiguous identities, stale/unknown evidence, pending/rejected approval, or explicit uncertainty fail closed before downstream authorization review.

## Data and test boundary

Repository tests use synthetic students, assignments, rubric evidence, scores, feedback, provenance, and platform names only. Real student data and production LMS/SIS captures do not belong in repository fixtures.

WS-GRADE1 performs no browser execution, LMS/SIS login, API integration, grade mutation, or external write.
