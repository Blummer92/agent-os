import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import test from 'node:test';

import {
  CAPTURE_HOST_ENTRYPOINTS,
  captureGcloudArgv,
  captureHostEntrypoint,
  invokeGceCapture,
} from '../gce_capture_transport.mjs';
import {
  BROWSER_SESSION_REF,
  CANVA_BROWSER_SESSION_REF,
  EXECUTION_SURFACE,
  PRIVACY_MODE,
} from '../live_capture_request.mjs';
import { fingerprintRecording } from '../safe_recording.mjs';

const rawRecording = JSON.stringify({ title: 'Synthetic', steps: [] });

function payload(overrides = {}) {
  return {
    operation: 'captureFlow',
    execution_surface: EXECUTION_SURFACE,
    capture_request_id: 'tutorial0-canva',
    target_url: 'https://www.canva.com/',
    approved_origins: ['https://www.canva.com'],
    recording_sha256: fingerprintRecording(rawRecording),
    recording_content_ref: 'recorder/tutorial0-canva.json',
    browser_session_ref: CANVA_BROWSER_SESSION_REF,
    authentication_status: 'AUTH_READY',
    privacy_mode: PRIVACY_MODE,
    raw_recording: rawRecording,
    ...overrides,
  };
}

function successfulSpawn(observed) {
  return (command, argv, options) => {
    observed.command = command;
    observed.argv = argv;
    observed.options = options;
    const child = new EventEmitter();
    child.stdin = new PassThrough();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    observed.stdin = '';
    child.stdin.on('data', (chunk) => { observed.stdin += chunk.toString('utf8'); });
    child.kill = () => {};
    queueMicrotask(() => {
      child.stdout.end(JSON.stringify({
        transport_status: 'succeeded',
        execution_surface: EXECUTION_SURFACE,
        capture_result: { status: 'blocked', capture: null },
        side_effects_performed: false,
      }));
      child.stderr.end();
      child.emit('close', 0);
    });
    return child;
  };
}

test('GCE capture argv is fixed to one host and one session-owned entrypoint', () => {
  assert.equal(captureHostEntrypoint(CANVA_BROWSER_SESSION_REF), CAPTURE_HOST_ENTRYPOINTS[CANVA_BROWSER_SESSION_REF]);
  assert.equal(captureHostEntrypoint(BROWSER_SESSION_REF), CAPTURE_HOST_ENTRYPOINTS[BROWSER_SESSION_REF]);
  assert.throws(() => captureHostEntrypoint('other-session'), /unsupported browser session/);

  const argv = captureGcloudArgv(CANVA_BROWSER_SESSION_REF);
  assert.deepEqual(argv, [
    'compute', 'ssh', 'agent-os-test',
    '--project', 'agent-os-502614',
    '--zone', 'us-central1-a',
    '--tunnel-through-iap',
    '--quiet',
    '--command', 'sudo -n /usr/local/libexec/agent-os-canva-software-tutorial-capture',
  ]);
  assert.equal(argv.some((value) => /bash|sh -c|node -e|python -c/.test(value)), false);
});

test('valid capture payload streams exact bytes over stdin without a local shell', async () => {
  const observed = {};
  const result = await invokeGceCapture(payload(), { spawnImpl: successfulSpawn(observed), timeoutMs: 1000 });
  assert.equal(observed.command, 'gcloud');
  assert.equal(observed.options.shell, false);
  assert.deepEqual(observed.argv, captureGcloudArgv(CANVA_BROWSER_SESSION_REF));
  const sent = JSON.parse(observed.stdin);
  assert.equal(sent.raw_recording, rawRecording);
  assert.equal(sent.recording_sha256, fingerprintRecording(rawRecording));
  assert.equal(sent.browser_session_ref, CANVA_BROWSER_SESSION_REF);
  assert.equal(result.transport_status, 'succeeded');
});

test('unknown or arbitrary transport fields are not representable', async () => {
  for (const extra of [
    { command: 'id' },
    { script: 'echo nope' },
    { argv: ['sh'] },
    { profile_path: '/tmp/profile' },
    { display: ':1' },
    { port: 9222 },
    { executable_path: '/bin/sh' },
    { launch_args: ['--remote-debugging-port=9222'] },
    { password: 'secret' },
    { token: 'secret' },
    { cookie: 'secret' },
  ]) {
    await assert.rejects(() => invokeGceCapture({ ...payload(), ...extra }, { spawnImpl: () => { throw new Error('must not spawn'); } }));
  }
});

test('capture transport rejects non-ready auth and alternate execution surfaces before spawn', async () => {
  let spawned = false;
  const spawnImpl = () => { spawned = true; throw new Error('must not spawn'); };
  await assert.rejects(() => invokeGceCapture(payload({ authentication_status: 'AUTH_REQUIRED' }), { spawnImpl }));
  await assert.rejects(() => invokeGceCapture(payload({ execution_surface: { ...EXECUTION_SURFACE, instance: 'other' } }), { spawnImpl }));
  assert.equal(spawned, false);
});
