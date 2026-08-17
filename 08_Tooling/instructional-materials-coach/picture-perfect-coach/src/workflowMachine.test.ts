import { createActor } from 'xstate';
import { picturePerfectMachine } from './workflowMachine';

describe('Picture Perfect workflow machine', () => {
  it('ignores illegal transitions and stays fail-closed', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'CONTINUE_TO_REVIEW' });
    expect(actor.getSnapshot().value).toBe('model_guidance');
    actor.stop();
  });

  it('allows only the bounded Model to Upload to Review-boundary path', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'CONTINUE_TO_UPLOAD' });
    expect(actor.getSnapshot().value).toBe('awaiting_upload');
    actor.send({ type: 'UPLOAD_SELECTED' });
    expect(actor.getSnapshot().value).toBe('validating_upload');
    actor.send({ type: 'UPLOAD_VALID' });
    expect(actor.getSnapshot().value).toBe('upload_valid');
    actor.send({ type: 'CONTINUE_TO_REVIEW' });
    expect(actor.getSnapshot().value).toBe('ready_for_review');
    actor.stop();
  });
});
