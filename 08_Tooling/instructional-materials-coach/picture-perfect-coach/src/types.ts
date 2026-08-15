export type EvidenceState = 'pending' | 'passed' | 'failed' | 'indeterminate' | 'unavailable';
export type ModelingDisposition = 'keep' | 'combine' | 'not-instructional' | 'needs-review';

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
  semantic_action_ids: string[];
  source: {
    candidate_id: string;
    recording_id: string;
    recording_sha256: string;
    source_indexes: number[];
    rj3_state: EvidenceState;
    rj4_state: EvidenceState;
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
    }
  | {
      ok: false;
      message: string;
    };
