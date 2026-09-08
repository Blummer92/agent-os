import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { createRunner, parse, PuppeteerRunnerExtension } from '@puppeteer/replay';
import puppeteer from 'puppeteer';

import { SUPPORTED_REPLAY_VERSION, validateRecorderConformance } from './recorder_conformance.mjs';

export const RJ4_FIXTURE_VERSION = 'rj4-synthetic-fixture-v1';
export const RJ4_STATUSES = Object.freeze(['equivalent', 'not-equivalent', 'indeterminate', 'runner-unavailable']);

const here = dirname(fileURLToPath(import.meta.url));
const fixturePath = resolve(here, 'test', 'fixtures', 'rj4-app.html');
const ALLOWED_URL_PREFIXES = ['about:blank', 'data:text/html'];

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function boundedFailure(code) {
  return Object.freeze({ reason_code: code });
}

function normalizeState(raw) {
  return Object.freeze({
    folder: raw.folder ?? '',
    title: raw.title ?? '',
    mode: raw.mode ?? '',
    modal: raw.modal ?? 'closed',
    error: raw.error ?? '',
    recovered: Boolean(raw.recovered),
    ready: Boolean(raw.ready),
  });
}

export function compareReplayEvidence(original, candidate) {
  if (original.status !== 'passed' || candidate.status !== 'passed') {
    const status = original.status === 'runner-unavailable' || candidate.status === 'runner-unavailable'
      ? 'runner-unavailable'
      : 'indeterminate';
    return Object.freeze({ status, behaviorally_safe: false, reason_code: `rj4-${status}` });
  }

  const sameCheckpoints = JSON.stringify(original.checkpoints) === JSON.stringify(candidate.checkpoints);
  const sameFinalState = JSON.stringify(original.final_state) === JSON.stringify(candidate.final_state);
  if (!sameCheckpoints || !sameFinalState) {
    return Object.freeze({ status: 'not-equivalent', behaviorally_safe: false, reason_code: 'rj4-observable-mismatch' });
  }
  return Object.freeze({ status: 'equivalent', behaviorally_safe: true, reason_code: null });
}

class RJ4Extension extends PuppeteerRunnerExtension {
  constructor(browser, page, { timeout }) {
    super(browser, page, { timeout });
    this.checkpoints = [];
  }

  async afterEachStep(step, flow) {
    await super.afterEachStep(step, flow);
    const checkpoint = await readObservableState(this.page);
    const previous = this.checkpoints.at(-1);
    if (!previous || JSON.stringify(previous) !== JSON.stringify(checkpoint)) this.checkpoints.push(checkpoint);
  }
}

async function readObservableState(page) {
  const raw = await page.evaluate(() => ({
    folder: document.querySelector('[data-testid="folder"]')?.textContent ?? '',
    title: document.querySelector('[data-testid="title-value"]')?.textContent ?? '',
    mode: document.querySelector('[data-testid="mode"]')?.textContent ?? '',
    modal: document.querySelector('[data-testid="modal"]')?.open ? 'open' : 'closed',
    error: document.querySelector('[data-testid="error"]')?.textContent ?? '',
    recovered: document.querySelector('[data-testid="recovered"]')?.textContent === 'yes',
    ready: document.querySelector('[data-testid="ready"]')?.textContent === 'yes',
  }));
  return normalizeState(raw);
}

async function ensureLocalOnly(page) {
  await page.setRequestInterception(true);
  page.on('request', request => {
    const url = request.url();
    if (ALLOWED_URL_PREFIXES.some(prefix => url.startsWith(prefix))) request.continue();
    else request.abort('blockedbyclient');
  });
}

export async function runSyntheticReplay(rawRecording, {
  launch = options => puppeteer.launch(options),
  timeout = 3000,
  fixtureHtml,
} = {}) {
  const conformance = await validateRecorderConformance(rawRecording);
  if (conformance.status !== 'recorder-valid') {
    return Object.freeze({
      status: 'rejected-before-replay',
      conformance,
      replay_version: conformance.validator.version,
      checkpoints: Object.freeze([]),
      final_state: null,
      failure: boundedFailure('rj4-rj3-conformance-required'),
    });
  }

  let browser;
  try {
    browser = await launch({ headless: true });
  } catch {
    return Object.freeze({
      status: 'runner-unavailable',
      conformance,
      replay_version: SUPPORTED_REPLAY_VERSION,
      checkpoints: Object.freeze([]),
      final_state: null,
      failure: boundedFailure('rj4-runner-unavailable'),
    });
  }

  try {
    const pages = await browser.pages();
    const page = pages[0] ?? await browser.newPage();
    await ensureLocalOnly(page);
    const html = fixtureHtml ?? await readFile(fixturePath, 'utf8');
    await page.setContent(html, { waitUntil: 'domcontentloaded' });
    const startState = await readObservableState(page);
    const extension = new RJ4Extension(browser, page, { timeout });
    const runner = await createRunner(parse(JSON.parse(rawRecording)), extension);
    await runner.run();
    return Object.freeze({
      status: 'passed',
      conformance,
      replay_version: SUPPORTED_REPLAY_VERSION,
      start_state: startState,
      checkpoints: Object.freeze([...extension.checkpoints]),
      final_state: await readObservableState(page),
      failure: null,
    });
  } catch (error) {
    const name = error instanceof Error ? error.name : 'Error';
    return Object.freeze({
      status: name === 'TimeoutError' ? 'indeterminate' : 'failed',
      conformance,
      replay_version: SUPPORTED_REPLAY_VERSION,
      checkpoints: Object.freeze([]),
      final_state: null,
      failure: boundedFailure(name === 'TimeoutError' ? 'rj4-timeout-indeterminate' : 'rj4-replay-failed'),
    });
  } finally {
    await browser.close();
  }
}

export async function validateReplayEquivalence(originalRaw, candidateRaw, options = {}) {
  const fixtureHtml = options.fixtureHtml ?? await readFile(fixturePath, 'utf8');
  const fixtureDigest = sha256(Buffer.from(fixtureHtml, 'utf8'));
  const originalDigest = sha256(Buffer.from(originalRaw, 'utf8'));
  const candidateDigest = sha256(Buffer.from(candidateRaw, 'utf8'));
  const run = options.runReplay ?? ((raw) => runSyntheticReplay(raw, { ...options, fixtureHtml }));

  const candidateConformance = await validateRecorderConformance(candidateRaw);
  if (candidateConformance.status !== 'recorder-valid') {
    return Object.freeze({
      status: 'not-equivalent',
      behaviorally_safe: false,
      fixture_version: RJ4_FIXTURE_VERSION,
      fixture_sha256: fixtureDigest,
      original_sha256: originalDigest,
      candidate_sha256: candidateDigest,
      replay_version: candidateConformance.validator.version,
      original: null,
      candidate: Object.freeze({ status: 'rejected-before-replay', conformance: candidateConformance }),
      reason_code: 'rj4-rj3-conformance-required',
      external_write_authorized: false,
      production_authorized: false,
    });
  }

  const original = await run(originalRaw);
  const candidate = await run(candidateRaw);
  const comparison = compareReplayEvidence(original, candidate);
  return Object.freeze({
    ...comparison,
    fixture_version: RJ4_FIXTURE_VERSION,
    fixture_sha256: fixtureDigest,
    original_sha256: originalDigest,
    candidate_sha256: candidateDigest,
    replay_version: SUPPORTED_REPLAY_VERSION,
    original,
    candidate,
    external_write_authorized: false,
    production_authorized: false,
  });
}
