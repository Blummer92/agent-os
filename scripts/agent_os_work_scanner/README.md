# Work Scanner grading contracts

This package owns platform-neutral Work Scanner grading evidence and deterministic synthetic gradebook fixtures.

## WS-GRADE1 boundary

`grading_decision.py` defines the portable grading decision produced after grading evidence has been evaluated. It deliberately contains no Schoology, PowerSchool, browser, selector, URL, cookie, token, session, DOM, login, or write-execution details.

The contract binds resolved student and assignment identity evidence, rubric evidence, proposed score and feedback, confidence and uncertainty, teacher approval state, freshness, provenance, requested target platforms, and a deterministic decision identity.

A grading decision is **not write authority**. `write_authorized` is permanently false. A later separately governed authorization contract must approve the exact mutation before any platform writer can act.

## WS-GRADE2 synthetic gradebook fixture

`synthetic_gradebook.py` provides a deterministic, local-only test environment for downstream reader, writer, authorization, and verification contracts. It is behavioral simulation only; it is not a copy of any vendor page or API.

The baseline contains three synthetic learners, three synthetic assignments, numeric and missing scores, comments, and rubric-like criteria. Similar learner and assignment names intentionally support deterministic ambiguity tests.

### Fixture states

The fixture supports:

- editable and read-only modes;
- current and stale visible state;
- an explicit confirmation modal before a synthetic grade mutation becomes visible;
- a recoverable one-shot error state;
- stable `data-testid`-style selector evidence;
- deliberately fragile generated-looking selector evidence;
- deterministic selector-drift simulation;
- deterministic pagination and filtering; and
- grade mutation followed by visible readback.

Call `reset()` between cases. Reset restores the immutable baseline and clears mode, freshness, modal, pending-write, selector-drift, and recoverable-error state. `version` and `digest` identify the baseline fixture; the same baseline version/content yields the same digest regardless of mutations made before reset.

### Downstream adapter boundary

Schoology-, PowerSchool-, or future platform-specific adapters may use this fixture to test behaviors such as semantic matching, ambiguity, read-only handling, stale state, selector drift, confirmation, and readback. They must translate those behaviors into their own governed interfaces rather than treating fixture selectors or names as platform semantics.

Repository fixtures contain synthetic identities and values only. They contain no real student names, IDs, grades, classes, emails, URLs, screenshots, cookies, tokens, credentials, production DOM captures, third-party scripts, or network access.

WS-GRADE2 performs no production browser access, LMS/SIS scraping, API integration, real grade mutation, grade decision-making, or external write.
