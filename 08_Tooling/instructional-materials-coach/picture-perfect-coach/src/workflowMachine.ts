import { setup } from 'xstate';

export type PicturePerfectEvent =
  | { type: 'CONTINUE_TO_UPLOAD' }
  | { type: 'UPLOAD_SELECTED' }
  | { type: 'UPLOAD_VALID' }
  | { type: 'UPLOAD_REJECTED' }
  | { type: 'RETRY_UPLOAD' }
  | { type: 'CONTINUE_TO_REVIEW' }
  | { type: 'START_REVIEW' }
  | { type: 'ATTENTION_REQUIRED' }
  | { type: 'ATTENTION_RESOLVED' }
  | { type: 'APPROVE_TUTORIAL' };

export const picturePerfectMachine = setup({
  types: {} as { events: PicturePerfectEvent },
}).createMachine({
  id: 'picture-perfect-coach',
  initial: 'model_guidance',
  states: {
    model_guidance: { on: { CONTINUE_TO_UPLOAD: 'awaiting_upload' } },
    awaiting_upload: { on: { UPLOAD_SELECTED: 'validating_upload' } },
    validating_upload: { on: { UPLOAD_VALID: 'upload_valid', UPLOAD_REJECTED: 'upload_invalid' } },
    upload_invalid: { on: { RETRY_UPLOAD: 'awaiting_upload' } },
    upload_valid: { on: { CONTINUE_TO_REVIEW: 'ready_for_review' } },
    ready_for_review: { on: { START_REVIEW: 'reviewing_steps' } },
    reviewing_steps: { on: { ATTENTION_REQUIRED: 'review_attention_required', APPROVE_TUTORIAL: 'tutorial_approved' } },
    review_attention_required: { on: { ATTENTION_RESOLVED: 'reviewing_steps' } },
    tutorial_approved: {},
  },
});
