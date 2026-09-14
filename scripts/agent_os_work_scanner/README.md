# Work Scanner grading contracts

This package owns platform-neutral Work Scanner grading evidence, deterministic synthetic gradebook fixtures, and the read-only browser-reader evidence boundary.

## WS-GRADE1 boundary

`grading_decision.py` defines the portable grading decision produced after grading evidence has been evaluated. It deliberately contains no Schoology, PowerSchool, browser, selector, URL, cookie, token, session, DOM, login, or write-execution details.

The contract binds resolved student and assignment identity evidence, rubric evidence, proposed score and feedback, confidence and uncertainty, teacher approval state, freshness, provenance, requested target platforms, and a deterministic decision identity.

A grading decision is **not write authority**. `write_authorized` is permanently false. A later separately governed authorization contract must approve the exact mutation before any platform writer can act.

## WS-GRADE2 synthetic gradebook fixture

`synthetic_gradebook.py` provides a deterministic, local-only test environment for downstream reader, writer, authorization, and verification contracts. It is behavioral simulation only; it is not a copy of any vendor page or API.

The baseline contains three synthetic learners, three synthetic assignments, numeric and missing scores, comments, and rubric-like criteria. Similar learner and assignment names intentionally support deterministic ambiguity tests.

### Fixture states

The fixture supports editable/read-only modes, current/stale visible state, confirmation before synthetic mutation, recoverable errors, stable and fragile selector evidence, selector drift, pagination/filtering, reset, and visible grade readback.

Call `reset()` between cases. Reset restores the immutable baseline and clears mode, freshness, modal, pending-write, selector-drift, and recoverable-error state. `version` and `digest` identify the baseline fixture; the same baseline version/content yields the same digest regardless of mutations made before reset.

### Downstream adapter boundary

Schoology-, PowerSchool-, or future platform-specific adapters may use this fixture to test behaviors such as semantic matching, ambiguity, read-only handling, stale state, selector drift, confirmation, and readback. They must translate those behaviors into their own governed interfaces rather than treating fixture selectors or names as platform semantics.

Repository fixtures contain synthetic identities and values only. They contain no real student names, IDs, grades, classes, emails, URLs, screenshots, cookies, tokens, credentials, production DOM captures, third-party scripts, or network access.

WS-GRADE2 performs no production browser access, LMS/SIS scraping, API integration, real grade mutation, grade decision-making, or external write.

## WS-GRADE3 read-only reader boundary

`gradebook_reader.py` defines the normalized evidence contract that Schoology, PowerSchool, and future browser adapters translate into. The core contract carries platform/course identity, the existing WS-GRADE1 `IdentityEvidence` type for student and assignment identity, visible score/feedback, editability evidence, freshness, selector/evidence provenance, confidence, and a finite reader status.

The finite statuses are `read-success`, `ambiguous-student`, `ambiguous-assignment`, `not-found`, `read-only`, `stale-state`, `selector-drift`, `authentication-required`, `unsupported-page`, and `reader-error`. Successful reads require resolved student and assignment identities plus current evidence. Ambiguity and stale/read-only states are represented explicitly rather than guessed or promoted into authority.

`normalize_reader_record()` validates adapter output into the canonical contract and fails closed on malformed evidence. Canonical serialization produces a deterministic `gradebook-reader:<sha256>` evidence identity for the same normalized state.

The reader is strictly observational. `write_authorized` is permanently false, and the result exposes no grade mutation or form-submission method. Editability describes visible capability only; it never authorizes a write. Vendor-specific DOM selectors may appear only as bounded diagnostic provenance and must not enter the WS-GRADE1 grading decision contract.

WS-GRADE3 generic tests use the WS-GRADE2 synthetic fixture only. This contract performs no live browser automation, LMS/SIS login, API call, credential/session extraction, real-student-data handling, grade mutation, or external write. Vendor-specific browser mechanics belong to #1130/#1131; exact write authorization and post-write verification remain #1132/#1133.

## WS-GRADE4 Schoology read-only adapter boundary

`schoology_gradebook_adapter.py` translates already-observed, bounded Schoology-like gradebook evidence into the WS-GRADE3 `GradebookReaderResult`. It owns only Schoology-specific evidence normalization: course identity, candidate student/assignment identities, visible score/feedback, editability, freshness, page state, and bounded selector provenance.

Identity matching fails closed: zero candidates becomes `not-found`, multiple candidates become the corresponding ambiguity status, and exactly one candidate is required for resolved identity. Authentication-required, unsupported-page, selector-drift, stale, read-only, unknown-freshness, and reader-error states remain explicit finite outcomes rather than being promoted into success.

The adapter accepts normalized snapshot evidence; it does not fetch or scrape Schoology itself. Repository tests use synthetic Schoology-like values and selectors only. No real student records, production DOM captures, URLs, cookies, tokens, credentials, network interception, undocumented/private API, grade mutation, form submission, or external write is present. `write_authorized` remains permanently false through the WS-GRADE3 result.
