import assert from 'node:assert/strict';
import test from 'node:test';
import { runHostCapture } from '../live_capture_host.mjs';
import { EXECUTION_SURFACE, PRIVACY_MODE, SCHOOLOGY_BROWSER_SESSION_REF } from '../live_capture_request.mjs';
import { fingerprintRecording } from '../safe_recording.mjs';
const rawRecording = JSON.stringify({ title: 'Synthetic Schoology/Kami', steps: [{ type: 'navigate', url: 'https://dpscd.schoology.com/home' }] });
function input() { return { operation:'captureFlow', execution_surface:EXECUTION_SURFACE, capture_request_id:'schoology-kami-tutorial', target_url:'https://dpscd.schoology.com/home', approved_origins:['https://dpscd.schoology.com','https://web.kamihq.com'], recording_sha256:fingerprintRecording(rawRecording), recording_content_ref:'recorder/schoology-kami.json', browser_session_ref:SCHOOLOGY_BROWSER_SESSION_REF, authentication_status:'AUTH_READY', privacy_mode:PRIVACY_MODE, raw_recording:rawRecording }; }

test('Schoology host resolves only dedicated profile and auth probe', async () => {
  let config; let observed;
  const result = await runHostCapture(input(), { username:'agent-os-schoology-capture', authenticationProbeImpl: async (value) => { config = value; return 'AUTH_READY'; }, captureImpl: async (value) => { observed = value; return { status:'valid', capture:{ format_version:'software-tutorial-capture-v1', capture_id:'schoology-kami-tutorial', source:{ recording_sha256:fingerprintRecording(rawRecording) } } }; } });
  assert.deepEqual(config, { username:'agent-os-schoology-capture', profile:'/var/lib/agent-os/schoology-capture-home/.agent-os/browser-profiles/schoology-kami', authProbeUrl:'https://dpscd.schoology.com/home', expectedOrigin:'https://dpscd.schoology.com' });
  assert.equal(observed.userDataDir, config.profile); assert.equal(result.evidence_persisted, false);
});

test('Schoology host refuses another capture user', async () => {
  let invoked=false; const result=await runHostCapture(input(), { username:'agent-os-canva-capture', authenticationProbeImpl:async()=> 'AUTH_READY', captureImpl:async()=>{invoked=true;} });
  assert.equal(invoked,false); assert.equal(result.capture_result.failure.reason_code,'browser-session-user-mismatch');
});
