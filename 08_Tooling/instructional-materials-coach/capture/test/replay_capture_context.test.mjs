import assert from 'node:assert/strict';
import test from 'node:test';

import {
  resolveStepContext,
  resolveTargetEvidence,
} from '../replay_capture.mjs';

function frame(name, children = []) {
  return {
    name,
    childFrames: () => children,
    $: async (selector) => selector === '#hit'
      ? {
          boundingBox: async () => ({ x: 10, y: 20, width: 30, height: 40 }),
          evaluate: async () => ({}),
        }
      : null,
  };
}

function page(url, rootFrame) {
  return {
    url: () => url,
    mainFrame: () => rootFrame,
    viewport: () => ({ width: 100, height: 100 }),
    screenshot: async () => {},
  };
}

test('main target resolves the default page and its main frame', async () => {
  const root = frame('main');
  const defaultPage = page('https://school.example/course', root);
  const browser = { pages: async () => [defaultPage] };

  const context = await resolveStepContext(browser, defaultPage, { type: 'click', target: 'main' });
  assert.equal(context.status, 'resolved');
  assert.equal(context.page, defaultPage);
  assert.equal(context.query_context, root);
});

test('URL target resolves exactly one matching page', async () => {
  const school = page('https://school.example/course', frame('school'));
  const kamiRoot = frame('kami');
  const kami = page('https://kami.example/work', kamiRoot);
  const browser = { pages: async () => [school, kami] };

  const context = await resolveStepContext(browser, school, {
    type: 'click',
    target: 'https://kami.example/work',
  });
  assert.equal(context.status, 'resolved');
  assert.equal(context.page, kami);
  assert.equal(context.query_context, kamiRoot);
});

test('duplicate matching target pages fail ambiguous', async () => {
  const school = page('https://school.example/course', frame('school'));
  const kamiA = page('https://kami.example/work', frame('kami-a'));
  const kamiB = page('https://kami.example/work', frame('kami-b'));
  const browser = { pages: async () => [school, kamiA, kamiB] };

  const context = await resolveStepContext(browser, school, {
    type: 'click',
    target: 'https://kami.example/work',
  });
  assert.equal(context.status, 'ambiguous');
  assert.equal(context.reason_code, 'quality-target-ambiguous');
});

test('missing target page fails unresolved instead of falling back to main', async () => {
  const school = page('https://school.example/course', frame('school'));
  const browser = { pages: async () => [school] };

  const context = await resolveStepContext(browser, school, {
    type: 'click',
    target: 'https://kami.example/work',
  });
  assert.equal(context.status, 'unresolved');
  assert.equal(context.reason_code, 'quality-target-unresolved');
});

test('frame path resolves child-frame indexes in order', async () => {
  const leaf = frame('leaf');
  const nested = frame('nested', [frame('unused'), leaf]);
  const root = frame('root', [nested]);
  const school = page('https://school.example/course', root);
  const browser = { pages: async () => [school] };

  const context = await resolveStepContext(browser, school, {
    type: 'click',
    frame: [0, 1],
  });
  assert.equal(context.status, 'resolved');
  assert.equal(context.query_context, leaf);
});

test('missing child frame fails unresolved', async () => {
  const school = page('https://school.example/course', frame('root'));
  const browser = { pages: async () => [school] };

  const context = await resolveStepContext(browser, school, {
    type: 'click',
    frame: [0],
  });
  assert.equal(context.status, 'unresolved');
  assert.equal(context.reason_code, 'quality-target-unresolved');
});

test('target evidence queries the resolved frame context, not the page', async () => {
  const queryContext = frame('child');
  const evidencePage = page('https://school.example/course', frame('root'));
  evidencePage.$ = async () => {
    throw new Error('main page must not be queried');
  };

  const result = await resolveTargetEvidence(queryContext, evidencePage, {
    type: 'click',
    selectors: [['#hit']],
    offsetX: 5,
    offsetY: 6,
  });

  assert.deepEqual(result.selector_resolved, ['#hit']);
  assert.deepEqual(result.geometry, {
    target_x: 10,
    target_y: 20,
    target_width: 30,
    target_height: 40,
  });
  assert.deepEqual(result.derived_click, {
    derived_click_x: 15,
    derived_click_y: 26,
  });
});
