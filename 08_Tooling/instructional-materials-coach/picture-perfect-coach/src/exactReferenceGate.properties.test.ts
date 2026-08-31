/**
 * #1577 bounded Node/TypeScript property-testing pilot for `admitExactReference`.
 *
 * Every property below is derived from the gate's real contract in
 * `./exactReferenceGate` and its composed `./visualReference` helpers. Nothing
 * here asserts behaviour the production contract does not already promise.
 *
 * Determinism and offline execution: fast-check is seeded explicitly (`SEED`)
 * with an explicit `numRuns`, and it keeps no counterexample database, so a run
 * is fully reproducible and writes nothing. The gate itself is pure — no
 * network, filesystem, browser, provider, or clock input is reachable from it.
 *
 * `fast-check` is a bounded pilot dependency for #1577. Adopting it permanently
 * is #1578's decision, not this file's.
 */
import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import {
  admitExactReference,
  type ExactReferenceDecision,
  type ExactReferenceRequest,
} from './exactReferenceGate';
import type { ApprovedVisualReference, ReferenceRegion, ReferenceRegionSet } from './visualReference';

/** Fixed seed + run count: the whole point is a reproducible corpus. */
const SEED = 15771554;
const NUM_RUNS = 250;
const RUN_CONFIG = { seed: SEED, numRuns: NUM_RUNS } as const;

/**
 * Counts predicate invocations so a silent skip cannot masquerade as a pass.
 * On a green run fast-check performs no shrinking, so each property executes
 * exactly `NUM_RUNS` times and the total is exact.
 */
let executedExamples = 0;
const PROPERTY_COUNT = 12;

const REFERENCE: ApprovedVisualReference = {
  reference_id: 'adobe-elements-shapes',
  application: 'Adobe Express',
  application_variant: 'Education',
  context_state: 'editor/elements/shapes',
  captured_at: '2026-08-30T12:00:00Z',
  verified_at: '2026-08-30T12:05:00Z',
  sanitized_derivative_reference: 'sanitized://elements-shapes',
  source_reference: 'teacher-upload://elements-shapes',
  provenance: ['teacher-approved-source'],
  visible_ui_claims: ['Adobe Express', 'Elements', 'Shapes', 'circle', 'Fill color'],
  manifest_reference: {
    manifest_id: 'manifest-elements-shapes',
    record_revision: 1,
    fingerprint: 'manifest-fingerprint',
    verified_at: '2026-08-30T12:05:00Z',
    external_file_id: 'elements-shapes',
  },
  asset_reference: {
    asset_id: 'asset-elements-shapes',
    stable_ref: 'visual-reference://elements-shapes',
    content_fingerprint: 'fingerprint-elements-shapes',
  },
};

const LIBRARY = { references: [REFERENCE] } as const;

/**
 * Pairwise-disjoint rects. `admitReferenceRegions` blocks when a fill rect
 * intersects an anchor rect, so disjoint slots let `fill_allowed` vary freely
 * without collapsing the corpus onto one blocker.
 */
const DISJOINT_RECTS: readonly (readonly [number, number, number, number])[] = [
  [0.02, 0.02, 0.2, 0.2],
  [0.3, 0.02, 0.2, 0.2],
  [0.02, 0.3, 0.2, 0.2],
  [0.3, 0.3, 0.2, 0.2],
];

const REGION_IDS = ['elements-panel', 'shape-target', 'future-artwork', 'fill-control'] as const;
const UNKNOWN_REGION_ID = 'region-never-bound';

const claimArb = fc.oneof(
  { weight: 6, arbitrary: fc.constantFrom<string | null>(null, 'Elements', 'Shapes', 'circle', 'Fill color') },
  { weight: 1, arbitrary: fc.constant<string | null>('claim-not-visible') },
);

const regionRowsArb = fc.uniqueArray(
  fc.record({
    slot: fc.integer({ min: 0, max: DISJOINT_RECTS.length - 1 }),
    region_id: fc.constantFrom(...REGION_IDS),
    claim: claimArb,
    fill_allowed: fc.boolean(),
  }),
  { minLength: 1, maxLength: DISJOINT_RECTS.length, selector: (row) => row.slot },
);

/**
 * Broad regions: unique rect slots, but `region_id` may repeat, which is a real
 * fail-closed condition (`visual-reference-region-duplicate-id`) worth covering.
 */
const regionsArb: fc.Arbitrary<ReferenceRegion[]> = regionRowsArb.map((rows) =>
  rows.map((row) => ({
    region_id: row.region_id,
    claim: row.claim,
    rect: DISJOINT_RECTS[row.slot],
    fill_allowed: row.fill_allowed,
  })),
);

/**
 * Regions with `region_id` bound to the already-unique rect slot, so no
 * duplicate-id blocker can pre-empt the region checks these feed.
 *
 * fast-check found this distinction: an earlier version of the admissible
 * generator drew `region_id` freely, produced two regions sharing
 * `future-artwork`, and blocked on `visual-reference-region-duplicate-id`
 * instead of the required-region blocker the property expected. That was an
 * over-claiming property, not a gate defect. The minimized case is pinned as a
 * deterministic example in `./exactReferenceGate.test.ts`.
 */
const distinctRegionsArb: fc.Arbitrary<ReferenceRegion[]> = regionRowsArb.map((rows) =>
  rows.map((row) => ({
    region_id: REGION_IDS[row.slot],
    claim: row.claim,
    rect: DISJOINT_RECTS[row.slot],
    fill_allowed: row.fill_allowed,
  })),
);

const regionSetArb: fc.Arbitrary<ReferenceRegionSet> = fc.record({
  reference_id: fc.oneof(
    { weight: 6, arbitrary: fc.constant(REFERENCE.reference_id) },
    { weight: 1, arbitrary: fc.constant('some-other-reference') },
  ),
  content_fingerprint: fc.oneof(
    { weight: 6, arbitrary: fc.constant(REFERENCE.asset_reference.content_fingerprint) },
    { weight: 1, arbitrary: fc.constant('stale-fingerprint') },
  ),
  regions: regionsArb,
});

const selectionArb = fc.record({
  application: fc.oneof(
    { weight: 6, arbitrary: fc.constant('Adobe Express') },
    { weight: 1, arbitrary: fc.constantFrom('', 'Canva') },
  ),
  application_variant: fc.constantFrom<string | null | undefined>('Education', null, undefined),
  context_state: fc.oneof(
    { weight: 6, arbitrary: fc.constant('editor/elements/shapes') },
    { weight: 1, arbitrary: fc.constantFrom('', 'editor/media') },
  ),
  required_ui_claims: fc.subarray(['Elements', 'Shapes', 'circle', 'Fill color']),
});

const sourceKindArb = fc.oneof(
  { weight: 6, arbitrary: fc.constant<ExactReferenceRequest['source_kind']>('approved-source') },
  {
    weight: 3,
    arbitrary: fc.constantFrom<ExactReferenceRequest['source_kind']>(
      'synthetic-reconstruction',
      'prose-only',
      'none',
    ),
  },
);

const mostlyTrue = fc.oneof({ weight: 5, arbitrary: fc.constant(true) }, { weight: 1, arbitrary: fc.constant(false) });

/** Broad corpus: reaches admitted and every fail-closed branch. */
const requestArb: fc.Arbitrary<ExactReferenceRequest> = fc.record({
  library: fc.constant(LIBRARY),
  selection: selectionArb,
  region_set: fc.oneof(
    { weight: 6, arbitrary: regionSetArb },
    { weight: 1, arbitrary: fc.constant(null) },
  ),
  required_region_ids: fc.array(fc.constantFrom(...REGION_IDS, UNKNOWN_REGION_ID), { maxLength: 4 }),
  source_expected: fc.boolean(),
  routing_resolved: mostlyTrue,
  source_accessible: mostlyTrue,
  source_kind: sourceKindArb,
}) as fc.Arbitrary<ExactReferenceRequest>;

/**
 * Corpus restricted to requests that clear every fail-closed guard, so
 * properties about the admitted path are not vacuously satisfied by a request
 * that was already blocked upstream.
 */
const admissibleRequestArb: fc.Arbitrary<ExactReferenceRequest> = fc
  .record({
    regions: distinctRegionsArb,
    required_ui_claims: fc.subarray(['Elements', 'Shapes', 'circle']),
    source_expected: fc.boolean(),
  })
  .chain((core) => {
    const presentIds = [...new Set(core.regions.map((region) => region.region_id))];
    return fc.subarray(presentIds).map((requiredIds) => ({
      library: LIBRARY,
      selection: {
        application: 'Adobe Express',
        application_variant: 'Education',
        context_state: 'editor/elements/shapes',
        required_ui_claims: core.required_ui_claims,
      },
      region_set: {
        reference_id: REFERENCE.reference_id,
        content_fingerprint: REFERENCE.asset_reference.content_fingerprint,
        regions: core.regions.map((region) => ({ ...region, claim: null })),
      },
      required_region_ids: requiredIds,
      source_expected: core.source_expected,
      routing_resolved: true,
      source_accessible: true,
      source_kind: 'approved-source' as const,
    }));
  });

/**
 * The admission authority a decision confers, with reason multiplicity and
 * ordering normalized away. Multiplicity/order is deliberately excluded: the
 * gate's own upstream helpers (`admitReferenceRegions`, `eligibilityReasons`)
 * return de-duplicated reason sets, so the contract carries no promise about
 * how many times one reason appears or in what order.
 */
function authorityOf(decision: ExactReferenceDecision) {
  if (decision.status === 'admitted') {
    return {
      status: decision.status,
      reference_id: decision.reference_id,
      source_reference: decision.source_reference,
      fill_region_ids: [...decision.fill_region_ids],
      fidelity_claim: decision.fidelity_claim,
    };
  }
  return {
    status: decision.status,
    blocker_reasons: [...new Set(decision.blocker_reasons)].sort(),
    generated_reconstruction_allowed: decision.generated_reconstruction_allowed,
    fidelity_claim: decision.fidelity_claim,
  };
}

/** True when guard 1 (`!routing_resolved && source_expected`) does not fire. */
function routingGuardClear(request: ExactReferenceRequest): boolean {
  return request.routing_resolved || !request.source_expected;
}

describe('exactReferenceGate property pilot (#1577, fast-check)', () => {
  it('identical requests always produce identical decisions', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        expect(admitExactReference(request)).toEqual(admitExactReference(request));
      }),
      RUN_CONFIG,
    );
  });

  it('blocked decisions never grant generated reconstruction authority', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference(request);
        if (decision.status === 'blocked') {
          expect(decision.generated_reconstruction_allowed).toBe(false);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('blocked decisions never claim exact-source-bound fidelity', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference(request);
        if (decision.status === 'blocked') {
          expect(decision.fidelity_claim).toBeNull();
        }
      }),
      RUN_CONFIG,
    );
  });

  it('source_kind "none" always blocks', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({ ...request, source_kind: 'none' });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked' && routingGuardClear(request)) {
          expect(decision.blocker_reasons).toEqual(['exact-reference-source-missing']);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('prose-only sources always block', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({ ...request, source_kind: 'prose-only' });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked' && routingGuardClear(request)) {
          expect(decision.blocker_reasons).toEqual(['exact-reference-synthetic-source-rejected']);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('synthetic reconstruction always blocks', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({ ...request, source_kind: 'synthetic-reconstruction' });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked' && routingGuardClear(request)) {
          expect(decision.blocker_reasons).toEqual(['exact-reference-synthetic-source-rejected']);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('inaccessible approved sources always block', () => {
    fc.assert(
      fc.property(admissibleRequestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({ ...request, source_accessible: false });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked') {
          expect(decision.blocker_reasons).toEqual(['exact-reference-source-inaccessible']);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('unresolved routing with an expected source always blocks', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({
          ...request,
          routing_resolved: false,
          source_expected: true,
        });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked') {
          expect(decision.blocker_reasons).toEqual(['exact-reference-routing-unresolved']);
        }
      }),
      RUN_CONFIG,
    );
  });

  it('missing required regions always block an otherwise admissible request', () => {
    fc.assert(
      fc.property(admissibleRequestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference({
          ...request,
          required_region_ids: [...request.required_region_ids, UNKNOWN_REGION_ID],
        });
        expect(decision.status).toBe('blocked');
        if (decision.status === 'blocked') {
          expect(decision.blocker_reasons).toContain(
            `exact-reference-required-region-missing:${UNKNOWN_REGION_ID}`,
          );
        }
      }),
      RUN_CONFIG,
    );
  });

  it('duplicate required_region_ids do not create new authority', () => {
    fc.assert(
      fc.property(
        requestArb.chain((request) =>
          (request.required_region_ids.length === 0
            ? fc.constant<readonly string[]>([])
            : fc.subarray([...request.required_region_ids], { minLength: 1 })
          ).map((extra) => ({ request, extra })),
        ),
        ({ request, extra }) => {
          executedExamples += 1;
          const baseline = admitExactReference(request);
          const duplicated = admitExactReference({
            ...request,
            required_region_ids: [...request.required_region_ids, ...extra],
          });
          expect(authorityOf(duplicated)).toEqual(authorityOf(baseline));
        },
      ),
      RUN_CONFIG,
    );
  });

  it('reordering required_region_ids does not change admission semantics', () => {
    fc.assert(
      fc.property(
        requestArb.chain((request) =>
          fc
            .shuffledSubarray([...request.required_region_ids], {
              minLength: request.required_region_ids.length,
              maxLength: request.required_region_ids.length,
            })
            .map((permuted) => ({ request, permuted })),
        ),
        ({ request, permuted }) => {
          executedExamples += 1;
          const baseline = admitExactReference(request);
          const reordered = admitExactReference({ ...request, required_region_ids: permuted });
          expect(authorityOf(reordered)).toEqual(authorityOf(baseline));
        },
      ),
      RUN_CONFIG,
    );
  });

  it('an admitted decision implies every fail-closed precondition held', () => {
    fc.assert(
      fc.property(requestArb, (request) => {
        executedExamples += 1;
        const decision = admitExactReference(request);
        if (decision.status === 'admitted') {
          expect(request.source_kind).toBe('approved-source');
          expect(request.source_accessible).toBe(true);
          expect(routingGuardClear(request)).toBe(true);
          expect(request.region_set).not.toBeNull();
          expect(decision.fidelity_claim).toBe('exact-source-bound');
        }
      }),
      RUN_CONFIG,
    );
  });
});

describe('property-pilot execution evidence (#1577)', () => {
  /**
   * A corpus that only ever reaches one blocker would satisfy every
   * "always blocks" property vacuously. This pins that the seeded corpus really
   * exercises admission and the distinct fail-closed branches.
   */
  it('the seeded corpus reaches admitted and multiple distinct blocker classes', () => {
    const corpus = fc.sample(requestArb, RUN_CONFIG);
    expect(corpus).toHaveLength(NUM_RUNS);

    const decisions = corpus.map(admitExactReference);
    const admitted = decisions.filter((decision) => decision.status === 'admitted');
    const reasons = new Set(
      decisions.flatMap((decision) => (decision.status === 'blocked' ? decision.blocker_reasons : [])),
    );

    expect(admitted.length).toBeGreaterThan(0);
    expect(reasons.has('exact-reference-source-missing')).toBe(true);
    expect(reasons.has('exact-reference-synthetic-source-rejected')).toBe(true);
    expect(reasons.has('exact-reference-routing-unresolved')).toBe(true);
    expect(reasons.size).toBeGreaterThanOrEqual(4);
  });

  /**
   * Proof the generated properties actually ran. A skipped or silently
   * no-op fast-check integration cannot reach this count.
   */
  it('every property executed its full generated run count', () => {
    expect(executedExamples).toBe(PROPERTY_COUNT * NUM_RUNS);
  });
});
