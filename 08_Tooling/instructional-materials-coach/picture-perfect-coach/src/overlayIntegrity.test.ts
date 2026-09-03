import { describe, expect, it } from 'vitest';
import {
  AUTHORITY_SOURCES,
  ELEMENT_CATEGORIES,
  ELEMENT_CLASSIFICATIONS,
  FRAME_ELEMENT_KINDS,
  GATE_C_BLOCKER_REASONS,
  OUTPUT_CONTRACT_KINDS,
  PLAN_AUTHORITY_SOURCE,
  authorizedFootprint,
  plannedElementInventory,
  validateOverlayAuthority,
  type AdmittedSourceElement,
  type ExecutedElement,
  type OutputContractKind,
} from './overlayIntegrity';
import {
  GATE_A_BLOCKER_REASONS,
  GATE_B_BLOCKER_REASONS,
  buildExclusionMask,
  validatePixelFidelity,
  validateReportIntegrity,
} from './provenanceValidator';
import { createFixtureSource, renderExactCompositeFixture, toArtifact, withLocalizedRedraw } from './fixtures/exactCompositeFixture';
import { planSha256 } from './exactCompositePrimitives';
import {
  FORBIDDEN_EXECUTOR_BEHAVIOURS,
  type ExactCompositeExecutionRequest,
  type ExecutorProvenanceReport,
} from './executorContract';
import {
  DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
  RECT_CONVENTION,
  RECT_SPACES,
  RENDER_MODES,
  TUTORIAL_FRAME_PLAN_VERSION,
  type FrameOverlay,
  type TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL9 (#1495) authorized-overlay integrity and no-invented-annotation
 * regressions.
 *
 * The suite encodes both benchmark failure classes as privacy-safe fixtures: the
 * typography reproduction that gained a step badge, an instructional label, and
 * an arrow, and the artifact-only hamburger that gained an entire graphics-editor
 * environment. No live provider call, network access, or classroom capture is
 * required to prove either.
 */

const TARGET = 'add-content-button';
const FINGERPRINT = 'sha256:approved-image';

const spotlight: FrameOverlay = {
  overlay_id: 'spotlight-1',
  kind: 'spotlight',
  bounds: { space: RECT_SPACES.outputPixel, rect: [18, 10, 20, 14] },
  region_id: TARGET,
  boundary: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] },
  padding_px: 2,
  falloff_px: 2,
  falloff_function: 'smoothstep',
};

const badge: FrameOverlay = {
  overlay_id: 'badge-1',
  kind: 'badge',
  bounds: { space: RECT_SPACES.outputPixel, rect: [48, 16, 4, 4] },
  ordinal: 1,
  centre_x_px: 50,
  centre_y_px: 18,
};

/** Tip inside the admitted target rect: the arrow points at the real control. */
const arrow: FrameOverlay = {
  overlay_id: 'arrow-1',
  kind: 'arrow',
  bounds: { space: RECT_SPACES.outputPixel, rect: [28, 16, 10, 4] },
  from_x_px: 37,
  from_y_px: 18,
  to_x_px: 28,
  to_y_px: 17,
};

function planWith(overrides: Partial<TutorialFramePlan> = {}): TutorialFramePlan {
  return {
    plan_version: TUTORIAL_FRAME_PLAN_VERSION,
    rect_convention: RECT_CONVENTION,
    base_reference: {
      reference_id: 'adobe-editor-add-content',
      stable_ref: 'asset://sanitized/editor-add-content',
      content_fingerprint: FINGERPRINT,
    },
    resolved_target_region_id: TARGET,
    source_rect: { space: RECT_SPACES.sourcePixel, rect: [0, 0, 64, 36] },
    output_aspect: { width: 16, height: 9 },
    output_width_px: 64,
    output_height_px: 36,
    render_mode: RENDER_MODES.cropOnly,
    scale_x: 1,
    scale_y: 1,
    render_spec: DEFAULT_EXACT_COMPOSITE_RENDER_SPEC,
    asset_fills: [],
    overlays: [spotlight, badge, arrow],
    anchored_rects: [{ region_id: TARGET, rect: { space: RECT_SPACES.outputPixel, rect: [20, 12, 16, 10] } }],
    must_show_region_ids: [TARGET],
    annotation_intent: { target_region_id: TARGET, label: 'Add content', preferred_side: 'right' },
    execution_authorized: false,
    ...overrides,
  };
}

const source = createFixtureSource(64, 36);
const plan = planWith();
const clean = renderExactCompositeFixture(plan, source);
const output = clean.image!;
const report = clean.report!;

const zeroOverlayPlan = planWith({ overlays: [] });
const zeroOverlayRender = renderExactCompositeFixture(zeroOverlayPlan, source);

function gateC(
  overrides: {
    plan?: TutorialFramePlan;
    contract?: OutputContractKind;
    elements?: readonly ExecutedElement[];
    report?: ExecutorProvenanceReport;
    fingerprint?: string;
    admitted?: readonly AdmittedSourceElement[];
  } = {},
) {
  const target = overrides.plan ?? plan;
  return validateOverlayAuthority({
    plan: target,
    output_contract: overrides.contract ?? OUTPUT_CONTRACT_KINDS.exactComposite,
    executed_elements: overrides.elements ?? plannedElementInventory(target),
    report: overrides.report ?? (target === plan ? report : renderExactCompositeFixture(target, source).report!),
    admitted_source_fingerprint: overrides.fingerprint ?? FINGERPRINT,
    admitted_source_elements: overrides.admitted,
  });
}

function invented(overrides: Partial<ExecutedElement> = {}): ExecutedElement {
  return {
    element_id: 'invented-1',
    category: ELEMENT_CATEGORIES.instructionalOverlay,
    kind: 'badge',
    classification: ELEMENT_CLASSIFICATIONS.ppuxAdded,
    claimed_authority: PLAN_AUTHORITY_SOURCE,
    claimed_target_region_id: TARGET,
    bounds: { space: RECT_SPACES.outputPixel, rect: [4, 4, 8, 8] },
    ...overrides,
  };
}

function editorChrome(kind: ExecutedElement['kind'], element_id: string): ExecutedElement {
  return {
    element_id,
    category: ELEMENT_CATEGORIES.outputFrame,
    kind,
    classification: ELEMENT_CLASSIFICATIONS.ppuxAdded,
    claimed_authority: PLAN_AUTHORITY_SOURCE,
    claimed_target_region_id: null,
    bounds: { space: RECT_SPACES.outputPixel, rect: [0, 0, 64, 8] },
  };
}

describe('#1495 overlay authority — positive controls', () => {
  it('case 1: correct source with a correctly targeted planned arrow passes every gate', () => {
    const authority = gateC();

    expect(authority.passed).toBe(true);
    expect(authority.blocker_reasons).toEqual([]);
    expect(authority.authorized_element_ids).toEqual(['spotlight-1', 'badge-1', 'arrow-1']);
    expect(authority.unauthorized_element_ids).toEqual([]);
    expect(validatePixelFidelity({ plan, source, output }).passed).toBe(true);
    expect(validateReportIntegrity({ plan, report, source, output }).passed).toBe(true);
  });

  it('every authorized element maps to exactly one plan record', () => {
    const inventory = plannedElementInventory(plan);

    expect(inventory.map((element) => element.element_id)).toEqual(plan.overlays.map((overlay) => overlay.overlay_id));
    expect(inventory.every((element) => element.claimed_authority === PLAN_AUTHORITY_SOURCE)).toBe(true);
    expect(plannedElementInventory(zeroOverlayPlan)).toEqual([]);
  });

  it('case 17: the gate is a pure fixture-driven function requiring no provider call', () => {
    expect(gateC()).toEqual(gateC());
    expect(zeroOverlayRender.status).toBe('valid');
  });

  it('context minimization: an execution request carries only the plan, the source, and approved assets', () => {
    const request: ExactCompositeExecutionRequest = { plan, source: toArtifact(source), assets: [] };

    expect(Object.keys(request).sort()).toEqual(['assets', 'plan', 'source']);
    for (const forbidden of ['locate-targets', 'recover-missing-plan-values', 'reconstruct-source-ui-or-artwork'] as const) {
      expect(FORBIDDEN_EXECUTOR_BEHAVIOURS).toContain(forbidden);
    }
  });
});

describe('#1495 zero-overlay authority', () => {
  it('case 6: a zero-overlay plan authorizes no element and excludes no pixel', () => {
    const authority = gateC({ plan: zeroOverlayPlan, elements: [] });

    expect(authority.passed).toBe(true);
    expect(authority.authorized_element_ids).toEqual([]);
    expect(buildExclusionMask(zeroOverlayPlan).excluded_fraction).toBe(0);
  });

  it('case 6: a tutorial instruction added under a zero-overlay plan is unauthorized in pixels and in authority', () => {
    const label = invented({ element_id: 'helpful-label-1', kind: 'label', bounds: { space: RECT_SPACES.outputPixel, rect: [10, 10, 20, 6] } });
    const authority = gateC({ plan: zeroOverlayPlan, elements: [label] });
    const painted = withLocalizedRedraw(zeroOverlayRender.image!, [10, 10, 20, 6]);
    const fidelity = validatePixelFidelity({ plan: zeroOverlayPlan, source, output: painted });

    expect(authority.passed).toBe(false);
    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized]);
    expect(authority.unauthorized_element_ids).toEqual(['helpful-label-1']);
    expect(fidelity.passed).toBe(false);
    expect(fidelity.blocker_reasons).toContain(GATE_A_BLOCKER_REASONS.maxAbsErrorExceeded);
  });

  it('case 11: prior conversation context cannot authorize an overlay under a zero-overlay plan', () => {
    const fromConversation = invented({
      element_id: 'conversation-badge-1',
      claimed_authority: AUTHORITY_SOURCES.conversationContext,
    });
    const authority = gateC({ plan: zeroOverlayPlan, elements: [fromConversation] });

    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.authoritySourceNotPlan]);
    expect(authority.authorized_element_ids).toEqual([]);
  });
});

describe('#1495 invented instructional annotation', () => {
  it('case 3: an extra badge beside a correct frame is unauthorized', () => {
    const authority = gateC({ elements: [...plannedElementInventory(plan), invented({ element_id: 'extra-badge-1' })] });

    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized]);
    expect(authority.unauthorized_element_ids).toEqual(['extra-badge-1']);
    expect(authority.authorized_element_ids).toEqual(['spotlight-1', 'badge-1', 'arrow-1']);
  });

  it('case 4: an unplanned spotlight is unauthorized', () => {
    const extra = invented({ element_id: 'extra-spotlight-1', kind: 'spotlight' });

    expect(gateC({ elements: [...plannedElementInventory(plan), extra] }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized]);
  });

  it('case 5: an unplanned instructional label or card is unauthorized', () => {
    const card = invented({ element_id: 'edit-the-selected-text', kind: 'label' });

    expect(gateC({ elements: [...plannedElementInventory(plan), card] }).unauthorized_element_ids)
      .toEqual(['edit-the-selected-text']);
  });

  it('an executed element that changes its plan record\'s kind is unauthorized', () => {
    const swapped = plannedElementInventory(plan).map((element) =>
      element.element_id === 'badge-1' ? { ...element, kind: 'label' as const } : element);

    expect(gateC({ elements: swapped }).blocker_reasons).toContain(GATE_C_BLOCKER_REASONS.overlayKindMismatch);
  });

  it('a plan overlay the execution never declared fails closed rather than being repaired', () => {
    const partial = plannedElementInventory(plan).filter((element) => element.element_id !== 'arrow-1');

    expect(gateC({ elements: partial }).blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayNotExecuted]);
  });

  it('a duplicated element identity is refused rather than deduplicated', () => {
    const inventory = plannedElementInventory(plan);

    expect(gateC({ elements: [...inventory, inventory[1]!] }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.duplicateElementId]);
  });
});

describe('#1495 target geometry', () => {
  it('case 2: an arrow pointing at a neighbouring control fails', () => {
    const neighbour = planWith({
      overlays: [spotlight, badge, { ...arrow, to_x_px: 44, to_y_px: 17 }],
    });

    expect(gateC({ plan: neighbour }).blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayTargetReinterpreted]);
  });

  it('case 9: an executor that reinterprets the target region from tutorial semantics fails', () => {
    const reinterpreted = plannedElementInventory(plan).map((element) =>
      element.element_id === 'arrow-1' ? { ...element, claimed_target_region_id: 'text-toolbar' } : element);

    expect(gateC({ elements: reinterpreted }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.overlayTargetReinterpreted]);
  });

  it('a spotlight boundary that drifts off the admitted target rect fails', () => {
    const drifted = planWith({
      overlays: [{ ...spotlight, boundary: { space: RECT_SPACES.outputPixel, rect: [21, 12, 16, 10] } }, badge, arrow],
    });

    expect(gateC({ plan: drifted }).blocker_reasons).toContain(GATE_C_BLOCKER_REASONS.overlayTargetReinterpreted);
  });

  it('an overlay whose target region was never admitted fails closed as an incomplete plan', () => {
    const unanchored = planWith({ anchored_rects: [] });

    expect(gateC({ plan: unanchored }).blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayTargetNotAdmitted]);
  });
});

describe('#1495 fixed masks and no post-hoc authority expansion', () => {
  it('an authorized footprint is derived from the plan alone', () => {
    expect(authorizedFootprint(plan, badge)).toEqual([46, 14, 8, 8]);
    expect(authorizedFootprint(plan, spotlight)).toEqual([16, 8, 24, 18]);
  });

  it('an element drawn wider than its plan record cannot widen its own footprint', () => {
    const widened = plannedElementInventory(plan).map((element) =>
      element.element_id === 'badge-1'
        ? { ...element, bounds: { space: RECT_SPACES.outputPixel, rect: [40, 10, 20, 20] as const } }
        : element);

    expect(gateC({ elements: widened }).blocker_reasons).toContain(GATE_C_BLOCKER_REASONS.overlayFootprintExpanded);
  });

  it('case 10: a report that widens the overlay bleed after output is refused', () => {
    const widened: ExecutorProvenanceReport = { ...report, overlay_bleed_px: 12 };

    expect(gateC({ report: widened }).blocker_reasons).toContain(GATE_C_BLOCKER_REASONS.postHocMaskExpansion);
    expect(validateReportIntegrity({ plan, report: widened, source, output }).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.overlayBleedMismatch);
  });

  it('case 10: adding an overlay to the plan after output breaks the plan binding', () => {
    const expanded = planWith({ overlays: [spotlight, badge, arrow, { ...badge, overlay_id: 'badge-2' }] });

    expect(planSha256(expanded)).not.toBe(report.plan_sha256);
    expect(validateReportIntegrity({ plan: expanded, report, source, output }).blocker_reasons)
      .toContain(GATE_B_BLOCKER_REASONS.planDigestMismatch);
  });

  it('a report overlay set that disagrees with the plan is not evaluated for authority', () => {
    const dropped: ExecutorProvenanceReport = { ...report, overlay_masks: report.overlay_masks.slice(0, 1) };

    expect(gateC({ report: dropped }).blocker_reasons).toContain(GATE_C_BLOCKER_REASONS.reportOverlayDrift);
  });
});

describe('#1495 artifact-only output', () => {
  const artifactPlan = zeroOverlayPlan;
  const artifactReport = zeroOverlayRender.report!;

  it('case 13: an artifact-only output that gains an editor window, panels, and toolbars fails', () => {
    const chrome = [
      editorChrome(FRAME_ELEMENT_KINDS.editorWindow, 'editor-window-1'),
      editorChrome(FRAME_ELEMENT_KINDS.layerPanel, 'layer-panel-1'),
      editorChrome(FRAME_ELEMENT_KINDS.toolbar, 'toolbar-1'),
    ];
    const authority = gateC({
      plan: artifactPlan,
      contract: OUTPUT_CONTRACT_KINDS.artifactOnly,
      elements: chrome,
      report: artifactReport,
    });

    expect(authority.passed).toBe(false);
    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.outputFrameNotAuthorized]);
    expect(authority.unauthorized_element_ids).toEqual(['editor-window-1', 'layer-panel-1', 'toolbar-1']);
  });

  it('case 14: knowing the originating application upstream does not authorize application chrome', () => {
    const fromApplication = {
      ...editorChrome(FRAME_ELEMENT_KINDS.applicationChrome, 'adobe-express-chrome-1'),
      claimed_authority: AUTHORITY_SOURCES.applicationIdentity,
    };
    const fromProcedure = {
      ...editorChrome(FRAME_ELEMENT_KINDS.tutorialUi, 'tutorial-ui-1'),
      claimed_authority: AUTHORITY_SOURCES.procedureProvenance,
    };
    const authority = gateC({
      plan: artifactPlan,
      contract: OUTPUT_CONTRACT_KINDS.artifactOnly,
      elements: [fromApplication, fromProcedure],
      report: artifactReport,
    });

    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.authoritySourceNotPlan]);
    expect(authority.authorized_element_ids).toEqual([]);
  });

  it('an artifact-only contract carrying planned overlays is an incoherent output contract', () => {
    expect(gateC({ contract: OUTPUT_CONTRACT_KINDS.artifactOnly }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.outputContractIncoherent]);
  });

  it('an unsupported output contract fails closed before any element is evaluated', () => {
    const authority = gateC({
      contract: 'annotated-editor-walkthrough' as OutputContractKind,
      elements: [invented()],
    });

    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.outputContractUnsupported]);
    expect(authority.unauthorized_element_ids).toEqual([]);
  });
});

describe('#1495 source-native evidence', () => {
  const nativeArrow: AdmittedSourceElement = {
    element_id: 'source-arrow-1',
    kind: 'arrow',
    bounds: { space: RECT_SPACES.outputPixel, rect: [2, 2, 6, 6] },
  };

  it('case 7: an arrow already present in admitted source stays source evidence, not a PPUX overlay', () => {
    const declared: ExecutedElement = {
      element_id: nativeArrow.element_id,
      category: ELEMENT_CATEGORIES.instructionalOverlay,
      kind: 'arrow',
      classification: ELEMENT_CLASSIFICATIONS.sourceNative,
      claimed_authority: AUTHORITY_SOURCES.providerInference,
      claimed_target_region_id: null,
      bounds: nativeArrow.bounds,
    };
    const authority = gateC({ elements: [...plannedElementInventory(plan), declared], admitted: [nativeArrow] });

    expect(authority.passed).toBe(true);
    expect(authority.source_native_element_ids).toEqual([nativeArrow.element_id]);
    expect(authority.unauthorized_element_ids).toEqual([]);
  });

  it('source-native editor chrome present in admitted source is preserved rather than refused', () => {
    const nativePanel: AdmittedSourceElement = {
      element_id: 'source-layer-panel-1',
      kind: FRAME_ELEMENT_KINDS.layerPanel,
      bounds: { space: RECT_SPACES.outputPixel, rect: [0, 28, 64, 8] },
    };
    const declared: ExecutedElement = {
      element_id: nativePanel.element_id,
      category: ELEMENT_CATEGORIES.outputFrame,
      kind: nativePanel.kind,
      classification: ELEMENT_CLASSIFICATIONS.sourceNative,
      claimed_authority: PLAN_AUTHORITY_SOURCE,
      claimed_target_region_id: null,
      bounds: nativePanel.bounds,
    };

    expect(gateC({ elements: [...plannedElementInventory(plan), declared], admitted: [nativePanel] }).passed).toBe(true);
  });

  it('an invented overlay cannot be laundered by declaring it source-native', () => {
    const laundered: ExecutedElement = {
      ...invented({ element_id: 'source-arrow-1', kind: 'arrow' }),
      classification: ELEMENT_CLASSIFICATIONS.sourceNative,
    };

    expect(gateC({ elements: [...plannedElementInventory(plan), laundered], admitted: [nativeArrow] }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.sourceNativeClaimUnadmitted]);
    expect(gateC({ elements: [...plannedElementInventory(plan), laundered] }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.sourceNativeClaimUnadmitted]);
  });

  it('case 8: an overlay over unadmitted or synthetic application state fails before overlay evaluation', () => {
    const authority = gateC({
      fingerprint: 'sha256:synthetic-editor-state',
      elements: [...plannedElementInventory(plan), invented({ element_id: 'extra-badge-1' })],
    });

    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.sourceEvidenceNotAdmitted]);
    expect(authority.unauthorized_element_ids).toEqual([]);
    expect(authority.authorized_element_ids).toEqual([]);
  });
});

describe('#1495 bounded fill authority', () => {
  it('case 16: a bounded fill region cannot place tutorial or editor chrome outside itself', () => {
    const beyondFill: ExecutedElement = {
      ...editorChrome(FRAME_ELEMENT_KINDS.toolbar, 'fill-toolbar-1'),
      claimed_authority: AUTHORITY_SOURCES.boundedFillRegion,
    };

    expect(gateC({ elements: [...plannedElementInventory(plan), beyondFill] }).blocker_reasons)
      .toEqual([GATE_C_BLOCKER_REASONS.fillRegionAuthorityExceeded]);
  });

  it('a bounded fill region is not overlay authority even inside its own destination', () => {
    const filled = planWith({
      asset_fills: [{
        fill_id: 'fill-1',
        asset_id: 'asset-1',
        asset_fingerprint: 'sha256:asset',
        destination: { space: RECT_SPACES.outputPixel, rect: [0, 0, 16, 16] },
      }],
    });
    const insideFill: ExecutedElement = {
      ...invented({ element_id: 'fill-badge-1' }),
      claimed_authority: AUTHORITY_SOURCES.boundedFillRegion,
    };
    const inventory = [...plannedElementInventory(filled), insideFill];

    expect(validateOverlayAuthority({
      plan: filled,
      output_contract: OUTPUT_CONTRACT_KINDS.exactComposite,
      executed_elements: inventory,
      report: { ...report, plan_sha256: planSha256(filled) },
      admitted_source_fingerprint: FINGERPRINT,
    }).blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.authoritySourceNotPlan]);
  });
});

describe('#1495 provider self-report is non-authoritative', () => {
  const narrated = (narrative: string, steps: readonly string[] = []): ExecutorProvenanceReport => ({
    ...report,
    diagnostics: { ...report.diagnostics, narrative, step_trace: steps },
  });

  it('case 12: calling an invented annotation helpful or intentional does not authorize it', () => {
    const helpful = narrated('I added a step badge and an "Edit the selected text" label to help the student.');
    const authority = gateC({ elements: [...plannedElementInventory(plan), invented({ element_id: 'helpful-badge-1' })], report: helpful });

    expect(authority.passed).toBe(false);
    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized]);
    expect(authority.self_report_claims).toContain(`narrative:${helpful.diagnostics.narrative}`);
  });

  it('case 15: acknowledging afterwards that the editor UI was unrequested does not cure the violation', () => {
    const acknowledged = narrated('The software interface was not part of the request; I will fix it next time.');
    const authority = gateC({
      plan: zeroOverlayPlan,
      contract: OUTPUT_CONTRACT_KINDS.artifactOnly,
      elements: [editorChrome(FRAME_ELEMENT_KINDS.editorWindow, 'editor-window-1')],
      report: { ...acknowledged, plan_sha256: planSha256(zeroOverlayPlan), overlay_masks: [] },
    });

    expect(authority.passed).toBe(false);
    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.outputFrameNotAuthorized]);
    expect(authority.self_report_claims).toHaveLength(1);
  });

  it('a pixel-faithful attestation changes no decision, and the narrative is recorded either way', () => {
    const attested = narrated('pixel faithful; source fidelity preserved; I followed the tutorial', ['crop', 'dim', 'overlay']);
    const compliant = gateC({ report: attested });
    const violating = gateC({ elements: [...plannedElementInventory(plan), invented()], report: attested });

    expect(compliant.blocker_reasons).toEqual(gateC().blocker_reasons);
    expect(violating.blocker_reasons).toEqual(gateC({ elements: [...plannedElementInventory(plan), invented()] }).blocker_reasons);
    expect(compliant.self_report_claims).toEqual([
      `narrative:${attested.diagnostics.narrative}`,
      'step:crop',
      'step:dim',
      'step:overlay',
    ]);
  });

  it('a recovered spotlight estimate is recorded as a diagnostic and authorizes nothing', () => {
    const estimated: ExecutorProvenanceReport = {
      ...report,
      diagnostics: {
        ...report.diagnostics,
        recovered_spotlight_estimate: {
          overlay_id: 'estimated-spotlight-1',
          boundary: { space: RECT_SPACES.outputPixel, rect: [0, 0, 12, 12] },
          padding_px: 2,
          falloff_px: 2,
          falloff_function: 'smoothstep',
        },
      },
    };
    const authority = gateC({
      elements: [...plannedElementInventory(plan), invented({ element_id: 'estimated-spotlight-1', kind: 'spotlight' })],
      report: estimated,
    });

    expect(authority.self_report_claims).toContain('recovered-spotlight-estimate:estimated-spotlight-1');
    expect(authority.blocker_reasons).toEqual([GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized]);
  });
});
