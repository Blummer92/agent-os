import { createActor } from 'xstate';
import { picturePerfectMachine } from './workflowMachine';

describe('Picture Perfect workflow machine', () => {
  it('ignores illegal transitions and stays fail-closed', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'APPROVE_TUTORIAL' });
    expect(actor.getSnapshot().value).toBe('model_guidance');
    actor.stop();
  });

  it('allows the bounded Model to Upload to Review path', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'CONTINUE_TO_UPLOAD' });
    actor.send({ type: 'UPLOAD_SELECTED' });
    actor.send({ type: 'UPLOAD_VALID' });
    actor.send({ type: 'CONTINUE_TO_REVIEW' });
    expect(actor.getSnapshot().value).toBe('ready_for_review');
    actor.send({ type: 'START_REVIEW' });
    expect(actor.getSnapshot().value).toBe('reviewing_steps');
    actor.stop();
  });

  it('keeps attention resolution and tutorial approval explicit', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'CONTINUE_TO_UPLOAD' });
    actor.send({ type: 'UPLOAD_SELECTED' });
    actor.send({ type: 'UPLOAD_VALID' });
    actor.send({ type: 'CONTINUE_TO_REVIEW' });
    actor.send({ type: 'START_REVIEW' });
    actor.send({ type: 'ATTENTION_REQUIRED' });
    expect(actor.getSnapshot().value).toBe('review_attention_required');
    actor.send({ type: 'APPROVE_TUTORIAL' });
    expect(actor.getSnapshot().value).toBe('review_attention_required');
    actor.send({ type: 'ATTENTION_RESOLVED' });
    actor.send({ type: 'APPROVE_TUTORIAL' });
    expect(actor.getSnapshot().value).toBe('tutorial_approved');
    actor.stop();
  });

  it('requires explicit prompt generation and review before Ready', () => {
    const actor = createActor(picturePerfectMachine).start();
    actor.send({ type: 'CONTINUE_TO_UPLOAD' });
    actor.send({ type: 'UPLOAD_SELECTED' });
    actor.send({ type: 'UPLOAD_VALID' });
    actor.send({ type: 'CONTINUE_TO_REVIEW' });
    actor.send({ type: 'START_REVIEW' });
    actor.send({ type: 'APPROVE_TUTORIAL' });
    actor.send({ type: 'OPEN_READY' });
    expect(actor.getSnapshot().value).toBe('tutorial_approved');
    actor.send({ type: 'GENERATE_PROMPTS' });
    expect(actor.getSnapshot().value).toBe('generating_prompts');
    actor.send({ type: 'PROMPTS_VALID' });
    expect(actor.getSnapshot().value).toBe('reviewing_prompts');
    actor.send({ type: 'OPEN_READY' });
    expect(actor.getSnapshot().value).toBe('running_preflight');
    actor.stop();
  });

  it('has no image/provider execution event or state', () => {
    const config = picturePerfectMachine.config;
    const stateNames = Object.keys(config.states ?? {});
    expect(stateNames).not.toContain('generating_image');
    expect(stateNames).not.toContain('provider_execution');
    expect(JSON.stringify(config)).not.toMatch(/GENERATE_IMAGE|EXECUTE_PROVIDER|SUBMIT_PROMPT|provider_execution/);
  });
});
