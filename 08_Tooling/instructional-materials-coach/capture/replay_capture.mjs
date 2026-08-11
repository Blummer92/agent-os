import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRunner, parse, PuppeteerRunnerExtension } from '@puppeteer/replay';
import puppeteer from 'puppeteer';
import {
  authenticationBlocker,
  buildCaptureEnvelope,
  fingerprintAction,
  validateRecording,
} from './safe_recording.mjs';

const SELECTOR_STEP_TYPES = new Set(['click', 'doubleClick', 'change', 'hover', 'scroll', 'waitForElement']);

function sanitizeCaptureId(value) {
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9._-]{0,79}$/i.test(value)) {
    throw new TypeError('captureId must be a bounded filename-safe identifier');
  }
  return value;
}

function selectorAsPuppeteer(selector) {
  if (typeof selector === 'string') return selector;
  if (Array.isArray(selector) && selector.length === 1 && typeof selector[0] === 'string') return selector[0];
  return null;
}

export async function resolveTargetEvidence(page, step) {
  if (!SELECTOR_STEP_TYPES.has(step.type) || !Array.isArray(step.selectors)) {
    return Object.freeze({ selector_resolved: null, selector_classification: null, target_type: 'UNKNOWN', geometry: null, derived_click: null, reason_code: null });
  }

  const matches = [];
  for (const selector of step.selectors) {
    const candidate = selectorAsPuppeteer(selector);
    if (!candidate) continue;
    try {
      const handle = await page.$(candidate);
      if (handle) matches.push({ selector, box: await handle.boundingBox() });
    } catch {
      // Replay remains authoritative for execution. Unsupported inspection selectors
      // are retained as evidence and simply cannot be pre-resolved here.
    }
  }

  if (matches.length === 0) {
    return Object.freeze({ selector_resolved: null, selector_classification: null, target_type: 'UNKNOWN', geometry: null, derived_click: null, reason_code: 'quality-target-unresolved' });
  }

  const first = matches[0];
  const geometry = first.box ? Object.freeze({ target_x: first.box.x, target_y: first.box.y, target_width: first.box.width, target_height: first.box.height }) : null;
  const derivedClick = geometry && typeof step.offsetX === 'number' && typeof step.offsetY === 'number'
    ? Object.freeze({ derived_click_x: geometry.target_x + step.offsetX, derived_click_y: geometry.target_y + step.offsetY })
    : null;

  return Object.freeze({ selector_resolved: structuredClone(first.selector), selector_classification: 'ACCEPTABLE', target_type: 'DOM', geometry, derived_click: derivedClick, reason_code: null });
}

class EvidenceCaptureExtension extends PuppeteerRunnerExtension {
  constructor(browser, page, { screenshotDir, timeout }) {
    super(browser, page, { timeout });
    this.screenshotDir = screenshotDir;
    this.actionEvidence = [];
    this.currentIndex = -1;
  }

  async beforeEachStep(step, flow) {
    this.currentIndex += 1;
    const beforeName = `${String(this.currentIndex).padStart(3, '0')}-before.png`;
    await this.page.screenshot({ path: resolve(this.screenshotDir, beforeName), fullPage: false });
    const target = await resolveTargetEvidence(this.page, step);
    this.actionEvidence[this.currentIndex] = {
      source_index: this.currentIndex,
      source_fingerprint: fingerprintAction(step),
      action_type: step.type,
      selector_alternatives: Array.isArray(step.selectors) ? structuredClone(step.selectors) : [],
      selector_resolved: target.selector_resolved,
      selector_classification: target.selector_classification,
      target_type: target.target_type,
      target_geometry: target.geometry,
      recorded_offset_x: typeof step.offsetX === 'number' ? step.offsetX : null,
      recorded_offset_y: typeof step.offsetY === 'number' ? step.offsetY : null,
      derived_click_x: target.derived_click?.derived_click_x ?? null,
      derived_click_y: target.derived_click?.derived_click_y ?? null,
      screenshot_before: beforeName,
      screenshot_after: null,
      execution_result: 'pending',
      reason_code: target.reason_code,
    };
    await super.beforeEachStep(step, flow);
  }

  async afterEachStep(step, flow) {
    await super.afterEachStep(step, flow);
    const afterName = `${String(this.currentIndex).padStart(3, '0')}-after.png`;
    await this.page.screenshot({ path: resolve(this.screenshotDir, afterName), fullPage: false });
    this.actionEvidence[this.currentIndex] = { ...this.actionEvidence[this.currentIndex], screenshot_after: afterName, execution_result: 'passed' };
  }
}

export async function captureFlow({
  rawRecording,
  approvedOrigins,
  captureId,
  capturedAt,
  userDataDir,
  screenshotDir,
  authenticationStatus,
  headless = false,
  timeout = 7000,
  launchOptions = {},
}) {
  const validation = validateRecording(rawRecording, { approvedOrigins });
  if (validation.status !== 'valid') return Object.freeze({ status: validation.status, validation, capture: null });

  const authReason = authenticationBlocker(authenticationStatus);
  if (authReason) {
    return Object.freeze({ status: 'blocked', validation, capture: null, authentication_status: authenticationStatus, failure: Object.freeze({ reason_code: authReason }) });
  }
  if (!userDataDir || typeof userDataDir !== 'string') throw new TypeError('userDataDir is required; use a dedicated profile outside the repository');
  if (typeof screenshotDir !== 'string' || screenshotDir.trim().length === 0) throw new TypeError('screenshotDir is required');
  sanitizeCaptureId(captureId);
  await mkdir(screenshotDir, { recursive: true });

  const parsed = parse(structuredClone(validation.recording));
  const browser = await puppeteer.launch({ ...launchOptions, userDataDir, headless });
  const pages = await browser.pages();
  const page = pages[0] ?? await browser.newPage();
  const extension = new EvidenceCaptureExtension(browser, page, { screenshotDir, timeout });

  try {
    const runner = await createRunner(parsed, extension);
    await runner.run();
    return Object.freeze({
      status: 'valid',
      validation,
      capture: buildCaptureEnvelope({ captureId, capturedAt, validation, actionEvidence: extension.actionEvidence }),
    });
  } catch (error) {
    return Object.freeze({ status: 'blocked', validation, capture: null, failure: Object.freeze({ reason_code: 'quality-replay-failed', error_name: error instanceof Error ? error.name : 'Error' }) });
  } finally {
    await browser.close();
  }
}
