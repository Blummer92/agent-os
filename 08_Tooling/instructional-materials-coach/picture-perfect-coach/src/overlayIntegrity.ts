import type { CaptureStatus } from './captureEvidence';
import type { ExecutorProvenanceReport } from './executorContract';
import type {
  FrameOverlay,
  OutputPixelRect,
  OverlayKind,
  RectXywh,
  TutorialFramePlan,
} from './framePlan';

/**
 * PPUX-VRL9 (#1495) Gate C -- authorized-overlay integrity.
 *
 * Gate A asks whether the pixels match what the plan says, and Gate B asks
 * whether the report can be believed. Neither asks the question this gate
 * exists for: *was this element allowed to be drawn at all?*
 *
 * The invariant is one sentence: **only the resolved plan authorizes PPUX-added
 * pixels.** Conversation history, tutorial-looking source state, application
 * identity, procedure provenance, provider reasoning, and provider helpfulness
 * are not authority, and this gate refuses to let any of them become authority
 * by being declared as one.
 *
 * Two failure classes from the benchmark evidence motivate it. A typography
 * reproduction gained a step badge, an `Edit the selected text` label, and an
 * arrow that the plan never contained. An artifact-only hamburger synthesis
 * gained an entire graphics-editor environment around the artifact. Both are the
 * same architectural failure: pixels appeared because a provider inferred a
 * helpful instructional or editor context.
 *
 * What this gate is not: it does not detect editor UI, recognise annotations,
 * score images, read text, or inspect content in any way. There is no OCR, no
 * computer vision, and no model scoring here or anywhere it depends on. It
 * compares a declared element inventory against plan authority and admitted
 * source evidence, and it compares geometry arithmetically.
 *
 * #1484 owns exact-composite planning, execution, and provenance validation and
 * is consumed unchanged. #1496 owns source admission, #1497 owns bounded
 * generated fill, and #1501 owns procedure-grounded content; none of them is
 * duplicated or widened here.
 */

/* -------------------------------------------------------------------------
 * Authority vocabulary
 * ---------------------------------------------------------------------- */

/**
 * Where an executed element claims its authority came from.
 *
 * Every value other than `resolved-plan` is a context-leakage claim: it names a
 * thing that may legitimately inform planning upstream but can never authorize a
 * pixel. They are enumerated rather than lumped into one `other` case because a
 * rejected element should say which leakage class it belonged to.
 */
export const AUTHORITY_SOURCES = {
  resolvedPlan: 'resolved-plan',
  boundedFillRegion: 'bounded-fill-region',
  conversationContext: 'conversation-context',
  applicationIdentity: 'application-identity',
  procedureProvenance: 'procedure-provenance',
  providerInference: 'provider-inference',
} as const;

export type AuthoritySource = (typeof AUTHORITY_SOURCES)[keyof typeof AUTHORITY_SOURCES];

/** The one source that can authorize a PPUX-added instructional overlay. */
export const PLAN_AUTHORITY_SOURCE = AUTHORITY_SOURCES.resolvedPlan;

/**
 * Non-overlay chrome a provider may add around an output. The exact-composite
 * plan has no record that authorizes any of these, so the list exists to name
 * what was drawn in a refusal, never to describe something admissible.
 */
export const FRAME_ELEMENT_KINDS = {
  applicationChrome: 'application-chrome',
  editorWindow: 'editor-window',
  layerPanel: 'layer-panel',
  toolbar: 'toolbar',
  control: 'control',
  tutorialUi: 'tutorial-ui',
  explanatoryFraming: 'explanatory-framing',
} as const;

export type FrameElementKind = (typeof FRAME_ELEMENT_KINDS)[keyof typeof FRAME_ELEMENT_KINDS];

export const ELEMENT_CATEGORIES = {
  instructionalOverlay: 'instructional-overlay',
  outputFrame: 'output-frame',
} as const;

export type ElementCategory = (typeof ELEMENT_CATEGORIES)[keyof typeof ELEMENT_CATEGORIES];

/**
 * `source-native` means the element already existed in admitted source evidence.
 * A source screenshot that genuinely contains an arrow, a badge, a toolbar, or a
 * layer panel keeps those pixels: they are source, not PPUX overlays, and they
 * are not unauthorized merely because they resemble tutorial annotation.
 */
export const ELEMENT_CLASSIFICATIONS = {
  ppuxAdded: 'ppux-added',
  sourceNative: 'source-native',
} as const;

export type ElementClassification =
  (typeof ELEMENT_CLASSIFICATIONS)[keyof typeof ELEMENT_CLASSIFICATIONS];

/**
 * `exact-composite` produces one tutorial frame from admitted source pixels and
 * may carry the overlays its plan contains. `artifact-only` produces the
 * finished student artifact and nothing else: no annotation, no framing, and no
 * application environment around it.
 */
export const OUTPUT_CONTRACT_KINDS = {
  exactComposite: 'exact-composite',
  artifactOnly: 'artifact-only',
} as const;

export type OutputContractKind =
  (typeof OUTPUT_CONTRACT_KINDS)[keyof typeof OUTPUT_CONTRACT_KINDS];

/* -------------------------------------------------------------------------
 * Evidence records
 * ---------------------------------------------------------------------- */

/**
 * One element an execution declares it drew.
 *
 * This inventory is evidence, never authority: it can only convict. A declared
 * element with no matching plan record is a violation, and a plan record with no
 * declared element is an incomplete execution. Nothing an executor writes here
 * can create permission for pixels -- including `claimed_authority`, which
 * records what the executor *believed* authorized it so that a leakage class can
 * be named in the refusal.
 */
export type ExecutedElement = Readonly<{
  element_id: string;
  category: ElementCategory;
  kind: OverlayKind | FrameElementKind;
  classification: ElementClassification;
  claimed_authority: AuthoritySource;
  /** The region the element claims to address; `null` when it claims none. */
  claimed_target_region_id: string | null;
  bounds: OutputPixelRect;
}>;

/**
 * An element already present in admitted source evidence, in output
 * coordinates. Admission is #1496's job; this gate consumes the result and uses
 * it only to keep source pixels from being mistaken for PPUX overlays.
 */
export type AdmittedSourceElement = Readonly<{
  element_id: string;
  kind: OverlayKind | FrameElementKind;
  bounds: OutputPixelRect;
}>;

export type OverlayAuthorityInput = Readonly<{
  plan: TutorialFramePlan;
  output_contract: OutputContractKind;
  executed_elements: readonly ExecutedElement[];
  /** Consulted for mask drift and for recording self-report; never for authority. */
  report: ExecutorProvenanceReport;
  /**
   * The content fingerprint of the source actually admitted upstream. A plan
   * built against different pixels -- a synthetic or hallucinated application
   * state, for instance -- fails here, before any overlay is evaluated.
   */
  admitted_source_fingerprint: string;
  admitted_source_elements?: readonly AdmittedSourceElement[];
}>;

export const GATE_C_BLOCKER_REASONS = {
  sourceEvidenceNotAdmitted: 'gate-c-source-evidence-not-admitted',
  outputContractUnsupported: 'gate-c-output-contract-unsupported',
  outputContractIncoherent: 'gate-c-output-contract-incoherent',
  duplicateElementId: 'gate-c-duplicate-element-id',
  authoritySourceNotPlan: 'gate-c-authority-source-not-plan',
  overlayNotPlanAuthorized: 'gate-c-overlay-not-plan-authorized',
  overlayNotExecuted: 'gate-c-overlay-not-executed',
  overlayKindMismatch: 'gate-c-overlay-kind-mismatch',
  overlayFootprintExpanded: 'gate-c-overlay-footprint-expanded',
  overlayTargetNotAdmitted: 'gate-c-overlay-target-not-admitted',
  overlayTargetReinterpreted: 'gate-c-overlay-target-reinterpreted',
  outputFrameNotAuthorized: 'gate-c-output-frame-not-authorized',
  sourceNativeClaimUnadmitted: 'gate-c-source-native-claim-unadmitted',
  fillRegionAuthorityExceeded: 'gate-c-fill-region-authority-exceeded',
  postHocMaskExpansion: 'gate-c-post-hoc-mask-expansion',
  reportOverlayDrift: 'gate-c-report-overlay-drift',
} as const;

export type GateCBlockerReason =
  (typeof GATE_C_BLOCKER_REASONS)[keyof typeof GATE_C_BLOCKER_REASONS];

export type OverlayAuthorityResult = Readonly<{
  status: CaptureStatus;
  passed: boolean;
  /** Elements the plan authorized and the execution actually declared. */
  authorized_element_ids: readonly string[];
  /** Declared elements that no plan record authorizes. */
  unauthorized_element_ids: readonly string[];
  /** Declared elements admitted as source pixels rather than PPUX overlays. */
  source_native_element_ids: readonly string[];
  /**
   * Executor self-report, recorded verbatim and never consulted. It is kept
   * because a false or self-incriminating narrative is itself useful evidence,
   * not because it can authorize or certify anything.
   */
  self_report_claims: readonly string[];
  blocker_reasons: readonly GateCBlockerReason[];
}>;

/* -------------------------------------------------------------------------
 * Geometry
 * ---------------------------------------------------------------------- */

function sameRect(left: RectXywh, right: RectXywh): boolean {
  return left.every((value, index) => value === right[index]);
}

function dilate(rect: RectXywh, grow: number, width: number, height: number): RectXywh {
  const [x, y, rectWidth, rectHeight] = rect;
  const left = Math.max(0, x - grow);
  const top = Math.max(0, y - grow);
  const right = Math.min(width, x + rectWidth + grow);
  const bottom = Math.min(height, y + rectHeight + grow);
  return [left, top, Math.max(0, right - left), Math.max(0, bottom - top)];
}

function unionRect(left: RectXywh, right: RectXywh): RectXywh {
  const minX = Math.min(left[0], right[0]);
  const minY = Math.min(left[1], right[1]);
  const maxX = Math.max(left[0] + left[2], right[0] + right[2]);
  const maxY = Math.max(left[1] + left[3], right[1] + right[3]);
  return [minX, minY, maxX - minX, maxY - minY];
}

function containsRect(outer: RectXywh, inner: RectXywh): boolean {
  return inner[0] >= outer[0] && inner[1] >= outer[1] &&
    inner[0] + inner[2] <= outer[0] + outer[2] &&
    inner[1] + inner[3] <= outer[1] + outer[3];
}

function pointInRect(rect: RectXywh, x: number, y: number): boolean {
  return x >= rect[0] && x < rect[0] + rect[2] && y >= rect[1] && y < rect[1] + rect[3];
}

/** L-infinity gap between two rects; 0 when they touch or overlap. */
function rectGap(left: RectXywh, right: RectXywh): number {
  const horizontal = Math.max(left[0] - (right[0] + right[2]), right[0] - (left[0] + left[2]), 0);
  const vertical = Math.max(left[1] - (right[1] + right[3]), right[1] - (left[1] + left[3]), 0);
  return Math.max(horizontal, vertical);
}

/**
 * The output-space area one plan overlay is allowed to occupy: its declared
 * bounds grown by the plan's anti-aliasing bleed, plus, for a spotlight, the
 * dimming ramp its own falloff adds around the boundary it holds open.
 *
 * This is derived from the plan and only from the plan, so an execution cannot
 * widen the area it is measured against by declaring larger bounds.
 */
export function authorizedFootprint(plan: TutorialFramePlan, overlay: FrameOverlay): RectXywh {
  const width = plan.output_width_px;
  const height = plan.output_height_px;
  const bleed = dilate(overlay.bounds.rect, plan.render_spec.overlay_bleed_px, width, height);
  if (overlay.kind !== 'spotlight') return bleed;
  return unionRect(bleed, dilate(overlay.boundary.rect, overlay.falloff_px, width, height));
}

/**
 * The region an overlay addresses. #1484 binds a spotlight to its own region and
 * leaves every other overlay kind addressing the frame's one resolved target, so
 * there is nothing to guess and nothing to detect.
 */
export function overlayTargetRegionId(plan: TutorialFramePlan, overlay: FrameOverlay): string {
  return overlay.kind === 'spotlight' ? overlay.region_id : plan.resolved_target_region_id;
}

function admittedTargetRect(plan: TutorialFramePlan, regionId: string): RectXywh | null {
  return plan.anchored_rects.find((anchored) => anchored.region_id === regionId)?.rect.rect ?? null;
}

/**
 * Whether an overlay's geometry still addresses the admitted target rect.
 *
 * A spotlight holds the target open, so its boundary must be exactly the
 * admitted rect. An arrow's authority is its tip, so the tip must land inside
 * the target rather than on a neighbouring control. A badge, label, or inset
 * sits beside what it annotates, so it must stay within the plan's own
 * annotation clearance of the target -- aesthetic placement is allowed to move
 * it, but not far enough to change which control a student reads it as.
 */
function targetGeometryHolds(
  plan: TutorialFramePlan,
  overlay: FrameOverlay,
  target: RectXywh,
): boolean {
  const clearance = plan.render_spec.annotation_clearance_px;
  const width = plan.output_width_px;
  const height = plan.output_height_px;
  switch (overlay.kind) {
    case 'spotlight':
      return sameRect(overlay.boundary.rect, target);
    case 'arrow':
      return pointInRect(target, overlay.to_x_px, overlay.to_y_px);
    case 'badge':
      return pointInRect(dilate(target, clearance, width, height), overlay.centre_x_px, overlay.centre_y_px);
    default:
      return rectGap(overlay.bounds.rect, target) <= clearance;
  }
}

/* -------------------------------------------------------------------------
 * Plan authority
 * ---------------------------------------------------------------------- */

/**
 * The inventory a compliant execution must declare for a plan: exactly one
 * element per plan overlay, and nothing else.
 *
 * This is the contract statement, not a source of authority -- it is derived
 * from the plan, so it cannot describe an element the plan does not contain. A
 * zero-overlay plan yields an empty inventory, which is the whole of the
 * zero-overlay guarantee: there is no element for a compliant execution to draw.
 */
export function plannedElementInventory(plan: TutorialFramePlan): readonly ExecutedElement[] {
  return plan.overlays.map((overlay) => ({
    element_id: overlay.overlay_id,
    category: ELEMENT_CATEGORIES.instructionalOverlay,
    kind: overlay.kind,
    classification: ELEMENT_CLASSIFICATIONS.ppuxAdded,
    claimed_authority: PLAN_AUTHORITY_SOURCE,
    claimed_target_region_id: overlayTargetRegionId(plan, overlay),
    bounds: overlay.bounds,
  }));
}

function selfReportClaims(report: ExecutorProvenanceReport): readonly string[] {
  const { diagnostics } = report;
  const claims: string[] = [];
  if (diagnostics.narrative !== null) claims.push(`narrative:${diagnostics.narrative}`);
  for (const step of diagnostics.step_trace ?? []) claims.push(`step:${step}`);
  if (diagnostics.recovered_spotlight_estimate !== null) {
    claims.push(`recovered-spotlight-estimate:${diagnostics.recovered_spotlight_estimate.overlay_id}`);
  }
  return claims;
}

/**
 * Gate C.
 *
 * Ordering matters once: source admission is checked first and returns
 * immediately, because an overlay drawn onto a synthetic or unadmitted
 * application state is not a geometry question. Everything after that
 * accumulates, so one run names every distinct way an output exceeded its
 * authority rather than only the first.
 *
 * The gate never repairs. An overlay the plan requires but the execution did not
 * declare fails closed as an incomplete execution; an overlay whose plan record
 * lacks admitted target geometry fails closed as an incomplete plan. Neither is
 * reconstructed from anything the executor said.
 */
export function validateOverlayAuthority(input: OverlayAuthorityInput): OverlayAuthorityResult {
  const { plan, report, executed_elements: elements } = input;
  const admittedSource = input.admitted_source_elements ?? [];
  const reasons = new Set<GateCBlockerReason>();
  const claims = selfReportClaims(report);

  const finish = (
    authorized: readonly string[] = [],
    unauthorized: readonly string[] = [],
    sourceNative: readonly string[] = [],
  ): OverlayAuthorityResult => ({
    status: reasons.size === 0 ? 'valid' : 'blocked',
    passed: reasons.size === 0,
    authorized_element_ids: authorized,
    unauthorized_element_ids: unauthorized,
    source_native_element_ids: sourceNative,
    self_report_claims: claims,
    blocker_reasons: [...reasons],
  });

  if (plan.base_reference.content_fingerprint !== input.admitted_source_fingerprint) {
    reasons.add(GATE_C_BLOCKER_REASONS.sourceEvidenceNotAdmitted);
    return finish();
  }

  const contract = input.output_contract;
  if (contract !== OUTPUT_CONTRACT_KINDS.exactComposite && contract !== OUTPUT_CONTRACT_KINDS.artifactOnly) {
    reasons.add(GATE_C_BLOCKER_REASONS.outputContractUnsupported);
    return finish();
  }
  if (contract === OUTPUT_CONTRACT_KINDS.artifactOnly && plan.overlays.length > 0) {
    reasons.add(GATE_C_BLOCKER_REASONS.outputContractIncoherent);
  }

  // The report is a second inventory of the same overlays. Where the two
  // disagree, neither is believed: Gate B rejects the report against the plan,
  // and this gate refuses to evaluate authority against a disputed set.
  const plannedMasks = plan.overlays.map((overlay) => `${overlay.overlay_id}:${overlay.kind}:${overlay.bounds.rect.join(',')}`);
  const reportedMasks = report.overlay_masks.map((mask) => `${mask.overlay_id}:${mask.kind}:${mask.bounds.rect.join(',')}`);
  if (plannedMasks.length !== reportedMasks.length ||
    plannedMasks.some((entry, index) => entry !== reportedMasks[index])) {
    reasons.add(GATE_C_BLOCKER_REASONS.reportOverlayDrift);
  }

  // Exclusions are fixed by the plan before execution. A report that declares a
  // wider bleed is asking for authority it was not given, after the fact.
  if (report.overlay_bleed_px > plan.render_spec.overlay_bleed_px) {
    reasons.add(GATE_C_BLOCKER_REASONS.postHocMaskExpansion);
  }

  const planned = new Map(plan.overlays.map((overlay) => [overlay.overlay_id, overlay]));
  const admitted = new Map(admittedSource.map((element) => [element.element_id, element]));
  const authorized: string[] = [];
  const unauthorized: string[] = [];
  const sourceNative: string[] = [];
  const seen = new Set<string>();
  const matched = new Set<string>();

  for (const element of elements) {
    if (seen.has(element.element_id)) {
      reasons.add(GATE_C_BLOCKER_REASONS.duplicateElementId);
      unauthorized.push(element.element_id);
      continue;
    }
    seen.add(element.element_id);

    if (element.classification === ELEMENT_CLASSIFICATIONS.sourceNative) {
      const admittedElement = admitted.get(element.element_id);
      if (!admittedElement || admittedElement.kind !== element.kind ||
        !sameRect(admittedElement.bounds.rect, element.bounds.rect)) {
        reasons.add(GATE_C_BLOCKER_REASONS.sourceNativeClaimUnadmitted);
        unauthorized.push(element.element_id);
        continue;
      }
      sourceNative.push(element.element_id);
      continue;
    }

    // A fill region authorizes pixels inside itself and nowhere else. #1497 owns
    // what may be generated within one; this gate only refuses to let one become
    // a licence for tutorial overlays or editor chrome beyond its destination.
    if (element.claimed_authority === AUTHORITY_SOURCES.boundedFillRegion) {
      const inside = plan.asset_fills.some((fill) => containsRect(fill.destination.rect, element.bounds.rect));
      reasons.add(inside
        ? GATE_C_BLOCKER_REASONS.authoritySourceNotPlan
        : GATE_C_BLOCKER_REASONS.fillRegionAuthorityExceeded);
      unauthorized.push(element.element_id);
      continue;
    }

    if (element.claimed_authority !== PLAN_AUTHORITY_SOURCE) {
      reasons.add(GATE_C_BLOCKER_REASONS.authoritySourceNotPlan);
      unauthorized.push(element.element_id);
      continue;
    }

    if (element.category === ELEMENT_CATEGORIES.outputFrame) {
      // No plan record authorizes application chrome, editor windows, panels,
      // toolbars, controls, tutorial UI, or explanatory framing. Claiming plan
      // authority for one does not create the record it would need.
      reasons.add(GATE_C_BLOCKER_REASONS.outputFrameNotAuthorized);
      unauthorized.push(element.element_id);
      continue;
    }

    const overlay = planned.get(element.element_id);
    if (!overlay) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayNotPlanAuthorized);
      unauthorized.push(element.element_id);
      continue;
    }
    matched.add(element.element_id);

    let elementAuthorized = true;
    if (overlay.kind !== element.kind) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayKindMismatch);
      elementAuthorized = false;
    }
    if (!containsRect(authorizedFootprint(plan, overlay), element.bounds.rect)) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayFootprintExpanded);
      elementAuthorized = false;
    }

    const targetRegionId = overlayTargetRegionId(plan, overlay);
    if (element.claimed_target_region_id !== null && element.claimed_target_region_id !== targetRegionId) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayTargetReinterpreted);
      elementAuthorized = false;
    }

    const target = admittedTargetRect(plan, targetRegionId);
    if (target === null) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayTargetNotAdmitted);
      elementAuthorized = false;
    } else if (!targetGeometryHolds(plan, overlay, target)) {
      reasons.add(GATE_C_BLOCKER_REASONS.overlayTargetReinterpreted);
      elementAuthorized = false;
    }

    if (elementAuthorized) authorized.push(element.element_id);
    else unauthorized.push(element.element_id);
  }

  for (const overlay of plan.overlays) {
    if (!matched.has(overlay.overlay_id)) reasons.add(GATE_C_BLOCKER_REASONS.overlayNotExecuted);
  }

  return finish(authorized, unauthorized, sourceNative);
}
