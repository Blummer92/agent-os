import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import test from 'node:test';
const scripts = resolve(process.cwd(), '../../agent-os-execution-service/scripts');
const outer = resolve(scripts, 'agent-os-schoology-software-tutorial-capture');
const session = resolve(scripts, 'agent-os-schoology-software-tutorial-capture-session');
const installer = resolve(scripts, 'install-schoology-software-tutorial-capture');
async function text(path) { return readFile(path, 'utf8'); }
test('Schoology runtime is fixed and non-generic', async () => {
  const a=await text(outer); const b=await text(session); const c=await text(installer);
  assert.match(a,/CAPTURE_USER=agent-os-schoology-capture/); assert.match(b,/schoology-capture-home/); assert.match(c,/schoology-kami/); assert.match(c,/file_input_bindings\.mjs/);
  assert.doesNotMatch(a+b+c,/remote-debugging|profile_path|NOPASSWD: ALL/);
});
