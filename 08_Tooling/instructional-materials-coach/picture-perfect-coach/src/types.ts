import type { ActionIdentity, RecordingUiEvidence } from './uiEvidence';

export type EvidenceState = 'pending' | 'passed' | 'failed' | 'indeterminate' | 'unavailable';
export type ModelingDisposition = 'keep' | 'combine' | 'not-instructional' | 'needs-review';
export type ReviewChoice = 'keep' | 'combine-with-previous' | 'not-instructional';

export interface RewriteEvidence {
  kind: string;
  confidence: string;
  source_indexes: number[];
}

export interface ModelingCandidateProjection {
  candidate_id: string;
  semantic_action_id: string;
  source_indexes: number[];
  action_kind: string;
  fragile: boolean;
  recovery: boolean;
  rewrite: RewriteEvidence | null;
  rj3_state: EvidenceState;
  rj4_state: EvidenceState;
  instructional_disposition: 'undecided';
  execution_authorized: false;
}

export interface ModelingStepProjection {
  step_id: string;
  sequence: number;
  disposition: ModelingDisposition;
  title?: string;
  student_action?: string | null;
  notice?: string | null;
  check?: string | null;
  semantic_action_ids: string[];
  source: {
    candidate_id: string;
    recording_id: string;
    recording_sha256: string;
    source_indexes: number[];
    rj3_state: EvidenceState;
    rj4_state: EvidenceState;
    fragile?: boolean;
    recovery?: boolean;
    /**
     * Modeled application identity as supplied by Teacher Modeling approved evidence.
     * null means evidence did not establish an application identity for this step;
     * consumers must never infer it from title/branding text instead.
     */
    modeled_application: string | null;
  };
  execution_authorized: false;
}

export interface UploadEvidenceProjection {
  recording_id: string;
  recording_sha256: string;
  recorder_step_count: number;
  rj3_state: EvidenceState;
  rj4_state: EvidenceState;
  modeling_candidates: ModelingCandidateProjection[];
  modeling_steps: ModelingStepProjection[];
  /**
   * UI-claim evidence derived from the approved recording itself (PPUX-F1).
   * Never supplied by authoring content and never derived from modeling
   * candidate `target`/`evidence` text, which are instructional descriptors
   * rather than observed interface text.
   */
  recording_evidence: RecordingUiEvidence;
}

export interface ReviewDecision {
  step_id: string;
  choice: ReviewChoice;
}

export interface ReviewedStepProjection {
  review_step_id: string;
  sequence: number;
  source_step_ids: string[];
  source_steps: ModelingStepProjection[];
  semantic_action_ids: string[];
  source_indexes: number[];
  recording_id: string;
  recording_sha256: string;
  /**
   * Modeled application identity carried forward from approved evidence.
   * null means no approved evidence established an application identity;
   * Stage 4 must block software-UI prompts rather than infer or invent one.
   */
  modeled_application: string | null;
  /**
   * Action identity for this reviewed step's own source indexes. Array position
   * alone is never sufficient identity; the fingerprint detects a recording edit
   * that shifts or replaces an action. PPUX-F2 joins capture evidence on both.
   * Combining steps concatenates identities and never flattens them.
   */
  action_identity: readonly ActionIdentity[];
  execution_authorized: false;
}

export interface ReviewedTutorialProjection {
  recording_id: string;
  recording_sha256: string;
  retained_steps: ReviewedStepProjection[];
  excluded_step_ids: string[];
  review_decisions: ReviewDecision[];
  recording_evidence: RecordingUiEvidence;
  execution_authorized: false;
}

export interface UploadSummary {
  actionsFound: number;
  instructionalCandidates: number;
  likelyNoiseRecovery: number;
  needsReview: number;
}

export interface SafeTechnicalDetails {
  recordingId: string;
  recordingSha256: string;
  rj3State: EvidenceState;
  rj4State: EvidenceState;
  actions: Array<{
    semanticActionId: string;
    actionKind: string;
    sourceIndexes: number[];
    fragile: boolean;
    recovery: boolean;
  }>;
}

export type UploadValidationResult =
  | {
      ok: true;
      summary: UploadSummary;
      technical: SafeTechnicalDetails;
      evidence: UploadEvidenceProjection;
    }
  | {
      ok: false;
      message: string;
    };
