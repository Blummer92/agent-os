import tutorial0Recording from './tutorial0-recording.json';
import { fingerprintAction } from '../uiEvidence';
import type {
  ApprovedScreenshotEvidence,
  CaptureAction,
  CaptureEvidenceBundle,
  ScreenshotRole,
} from '../captureEvidence';

const RECORDING_SHA256 = '0838ef96dc6bc21699b67e4d40b2cfd9e73153ff8698ed2d373802890668e5fc';
const steps = (tutorial0Recording as { steps: unknown[] }).steps;

const actions: CaptureAction[] = steps.map((step, sourceIndex) => ({
  source_index: sourceIndex,
  source_fingerprint: fingerprintAction(step),
  target_geometry: {
    target_x: 40 + sourceIndex,
    target_y: 60 + sourceIndex,
    target_width: 180,
    target_height: 44,
  },
  screenshot_before: `${String(sourceIndex).padStart(3, '0')}-before.png`,
  screenshot_after: `${String(sourceIndex).padStart(3, '0')}-after.png`,
}));

function syntheticSha(seed: number): string {
  return seed.toString(16).padStart(64, '0').slice(-64);
}

function approval(sourceIndex: number, role: ScreenshotRole, visibleUiClaims: readonly string[]): ApprovedScreenshotEvidence {
  const action = actions[sourceIndex];
  if (!action) throw new Error(`synthetic capture action ${sourceIndex} is missing`);
  const screenshotReference = role === 'before' ? action.screenshot_before : action.screenshot_after;
  if (!screenshotReference) throw new Error(`synthetic ${role} screenshot ${sourceIndex} is missing`);
  const suffix = `${String(sourceIndex).padStart(3, '0')}-${role}`;
  return {
    source_index: sourceIndex,
    source_fingerprint: action.source_fingerprint,
    screenshot_role: role,
    screenshot_reference: screenshotReference,
    visible_ui_claims: visibleUiClaims,
    manifest_reference: {
      manifest_id: `tutorial0-screen-${suffix}`,
      record_revision: 1,
      fingerprint: syntheticSha(1000 + sourceIndex * 2 + (role === 'after' ? 1 : 0)),
      verified_at: '2026-08-20T00:00:00Z',
      external_file_id: `synthetic-local-${suffix}`,
    },
    asset_reference: {
      asset_id: `screen-${suffix}`,
      stable_reference: `artifact-manifest:tutorial0-screen-${suffix}#screen-${suffix}`,
      content_fingerprint: syntheticSha(2000 + sourceIndex * 2 + (role === 'after' ? 1 : 0)),
    },
    artifact_manifest: {
      contract_version: 'curriculum-artifact-manifest-v1',
      privacy_resolved: true,
      rights_state: 'cleared-internal',
      classroom_readiness: 'ready',
    },
    compatibility: {
      contract_version: 'curriculum-visual-asset-compatibility-v2',
      classification: 'eligible',
      medium: 'screen-capture',
      representation_class: 'interface-capture',
      stale: false,
    },
  };
}

/**
 * Synthetic/privacy-safe evidence only. These screenshot observations prove the
 * F2 binding contract offline; they make no claim about live Adobe reliability.
 */
export const tutorial0SyntheticCapture: CaptureEvidenceBundle = {
  status: 'valid',
  capture: {
    format_version: 'software-tutorial-capture-v1',
    capture_id: 'tutorial0-picture-perfect-synthetic-capture',
    source: { recording_sha256: RECORDING_SHA256 },
    actions,
  },
  approved_screenshots: [
    approval(12, 'after', ['Your stuff', 'Digital Media', 'Tutorial 0 - Organize My Files']),
    approval(13, 'before', ['Create new']),
    approval(20, 'before', ['Landscape']),
    approval(20, 'after', ['Landscape']),
  ],
};
