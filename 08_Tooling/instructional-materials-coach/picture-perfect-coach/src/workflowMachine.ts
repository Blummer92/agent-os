import { setup } from 'xstate';

export type PicturePerfectEvent =
  | { type: 'CONTINUE_TO_UPLOAD' }
  | { type: 'UPLOAD_SELECTED' }
  | { type: 'UPLOAD_VALID' }
  | { type: 'UPLOAD_REJECTED' }
  | { type: 'RETRY_UPLOAD' }
  | { type: 'CONTINUE_TO_REVIEW' };

export const picturePerfectMachine = setup({
  types: {} as { events: PicturePerfectEvent },
}).createMachine({
  id: 'picture-perfect-coach',
  initial: 'model_guidance',
  states: {
    model_guidance: {
      on: { CONTINUE_TO_UPLOAD: 'awaiting_upload' },
    },
    awaiting_upload: {
      on: { UPLOAD_SELECTED: 'validating_upload' },
    },
    validating_upload: {
      on: {
        UPLOAD_VALID: 'upload_valid',
        UPLOAD_REJECTED: 'upload_invalid',
      },
    },
    upload_invalid: {
      on: { RETRY_UPLOAD: 'awaiting_upload' },
    },
    upload_valid: {
      on: { CONTINUE_TO_REVIEW: 'ready_for_review' },
    },
    ready_for_review: {},
  },
});
