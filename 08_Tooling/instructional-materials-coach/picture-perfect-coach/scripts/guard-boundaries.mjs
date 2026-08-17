import { readdir, readFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url));
const forbidden = [
  ['network fetch', /\bfetch\s*\(/],
  ['XMLHttpRequest', /\bXMLHttpRequest\b/],
  ['WebSocket', /\bWebSocket\b/],
  ['sendBeacon', /\bsendBeacon\b/],
  ['Puppeteer runtime', /from\s+['\"]puppeteer/],
  ['Playwright runtime', /from\s+['\"]@?playwright/],
  ['provider SDK', /from\s+['\"](?:openai|@google\/genai|@anthropic-ai|firebase)/],
];

async function files(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const found = [];
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...(await files(full)));
    else if (['.ts', '.tsx'].includes(extname(entry.name)) && !entry.name.endsWith('.test.ts') && !entry.name.endsWith('.test.tsx')) found.push(full);
  }
  return found;
}

for (const file of await files(sourceRoot)) {
  const content = await readFile(file, 'utf8');
  for (const [label, pattern] of forbidden) {
    if (pattern.test(content)) {
      throw new Error(`${label} capability is outside PPUX-A: ${file}`);
    }
  }
}

console.log('PPUX-A boundary guard passed: no browser/provider/network execution sink found.');
