import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';

const scripts = resolve(process.cwd(), '../../agent-os-execution-service/scripts');
const outerPath = resolve(scripts, 'agent-os-canva-software-tutorial-capture');
const sessionPath = resolve(scripts, 'agent-os-canva-software-tutorial-capture-session');
const installerPath = resolve(scripts, 'install-canva-software-tutorial-capture');

async function text(path) { return readFile(path, 'utf8'); }

test('fixed outer entrypoint accepts no argv and delegates only to the Canva capture user', async () => {
  const value = await text(outerPath);
  assert.match(value, /\[ "\$#" -eq 0 \]/);
  assert.match(value, /CAPTURE_USER=agent-os-canva-capture/);
  assert.match(value, /SESSION_ENTRYPOINT=\/usr\/local\/libexec\/agent-os-canva-software-tutorial-capture-session/);
  assert.match(value, /exec "\$RUNUSER" -u "\$CAPTURE_USER" -- "\$SESSION_ENTRYPOINT"/);
  assert.doesNotMatch(value, /\beval\b|sh -c|bash -c|\$\{@/);
});

test('fixed session entrypoint uses only repository-owned runtime and host module paths', async () => {
  const value = await text(sessionPath);
  assert.match(value, /\[ "\$#" -eq 0 \]/);
  assert.match(value, /NODE=\/opt\/agent-os\/software-tutorial-capture\/node\/bin\/node/);
  assert.match(value, /ENTRYPOINT=\/opt\/agent-os\/software-tutorial-capture\/package\/live_capture_host\.mjs/);
  assert.match(value, /HOME=\/var\/lib\/agent-os\/canva-capture-home/);
  assert.doesNotMatch(value, /profile_path|remote-debugging|--command|scp|rsync/);
});

test('installer pins Node and exact service-account sudo command without generic privilege', async () => {
  const value = await text(installerPath);
  assert.match(value, /NODE_VERSION=22\.16\.0/);
  assert.match(value, /NODE_SHA256=f4cb75bb036f0d0eddf6b79d9596df1aaab9ddccd6a20bf489be5abe9467e84e/);
  assert.match(value, /TRANSPORT_PRINCIPAL=sa_117278680011452280250/);
  assert.match(value, /SUDOERS_TARGET=\/etc\/sudoers\.d\/agent-os-canva-software-tutorial-capture/);
  assert.match(value, /printf '%s ALL=\(root\) NOPASSWD: %s/);
  assert.match(value, /visudo -c -f/);
  assert.match(value, /visudo -c/);
  assert.doesNotMatch(value, /NOPASSWD:\s*ALL|ALL=\(ALL|\/bin\/sh|\/bin\/bash|python3?\s*\*/);
});
