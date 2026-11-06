/**
 * Node conformance suite for the Apps Script placement transport.
 *
 * Pins the runtime seam contract of
 * ``apps-script/VisualPlacementTransport.gs`` exactly as it exists on the
 * governed main branch, using injected fake services only. The suite is the
 * executable route selected by the ``apps-script-conformance`` focused rule in
 * ``scripts/agent_os_remote_validation/validation_profiles.yml`` (issue #3751).
 *
 * Run: node --test apps-script/test/visual-placement-transport.conformance.test.mjs
 * (from ``08_Tooling/instructional-materials-coach``; no dependencies required).
 *
 * Known limitation pinned here deliberately: the docs branch still reports the
 * synthetic ``docs-child-<index>`` element id instead of the inserted child's
 * real id. Hardening that read-back is tracked by draft PR #3651; this suite
 * documents the current truthful behavior so the route is executable today.
 */
import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

function loadTransport() {
  const source = readFileSync(
    new URL('../VisualPlacementTransport.gs', import.meta.url),
    'utf8',
  );
  return new Function(`${source}\n;return VisualPlacementTransport;`)();
}

function validDocsRequest() {
  return {
    asset_id: 'asset-1',
    drive_file_id: 'drive-file-1',
    role_id: 'role-1',
    source_plan_id: 'plan-1',
    target: {
      artifact_type: 'docs',
      artifact_id: 'doc-1',
      marker: '[[IMG]]',
      container_id: 'doc-1-body',
      element_id: 'element-1',
      index: 1,
      bounds: null,
    },
  };
}

function makeDrive() {
  const blob = { blob: true };
  return {
    blob,
    getFileById(fileId) {
      assert.equal(fileId, 'drive-file-1');
      return { getBlob: () => blob };
    },
  };
}

function makeDocsBody(children, log) {
  return {
    getNumChildren: () => children.length,
    getChild: (index) => children[index],
    insertImage: (index, blob) => {
      log.push(['body.insertImage', index, blob]);
      const element = { inserted: true };
      children.splice(index, 0, element);
      return element;
    },
  };
}

function makeDocsChild(text, log) {
  return {
    getText: () => text,
    removeFromParent: () => log.push(['marker.removeFromParent']),
  };
}

function makeDocs(log) {
  const children = [
    makeDocsChild('intro paragraph', log),
    makeDocsChild('[[IMG]]', log),
    makeDocsChild('closing paragraph', log),
  ];
  return {
    openById: (artifactId) => {
      assert.equal(artifactId, 'doc-1');
      return {
        getBody: () => makeDocsBody(children, log),
        saveAndClose: () => log.push(['document.saveAndClose']),
      };
    },
  };
}

function makeSlides(log) {
  const image = {
    setLeft: (value) => log.push(['image.setLeft', value]),
    setTop: (value) => log.push(['image.setTop', value]),
    setWidth: (value) => log.push(['image.setWidth', value]),
    setHeight: (value) => log.push(['image.setHeight', value]),
    getObjectId: () => 'SLIDE_IMG_1',
  };
  const marker = { remove: () => log.push(['marker.remove']) };
  const slide = {
    getPageElementById: (elementId) => {
      assert.equal(elementId, 'element-1');
      return marker;
    },
    insertImage: (blob) => {
      log.push(['slide.insertImage', blob]);
      return image;
    },
  };
  return {
    openById: (artifactId) => {
      assert.equal(artifactId, 'doc-1');
      return {
        getSlideById: (containerId) => {
          assert.equal(containerId, 'doc-1-body');
          return slide;
        },
      };
    },
  };
}

test('validateRequest returns the validated docs request with default bounds', () => {
  const transport = loadTransport();
  const validated = transport.validateRequest(validDocsRequest());
  assert.equal(validated.asset_id, 'asset-1');
  assert.equal(validated.drive_file_id, 'drive-file-1');
  assert.equal(validated.role_id, 'role-1');
  assert.equal(validated.source_plan_id, 'plan-1');
  assert.equal(validated.target.artifact_type, 'docs');
  assert.equal(validated.target.artifact_id, 'doc-1');
  assert.equal(validated.target.marker, '[[IMG]]');
  assert.equal(validated.target.container_id, 'doc-1-body');
  assert.equal(validated.target.element_id, 'element-1');
  assert.equal(validated.target.index, 1);
  assert.equal(validated.target.bounds, null);
});

test('validateRequest trims surrounding whitespace from required strings', () => {
  const transport = loadTransport();
  const request = validDocsRequest();
  request.asset_id = '  asset-1  ';
  const validated = transport.validateRequest(request);
  assert.equal(validated.asset_id, 'asset-1');
});

test('validateRequest rejects a missing request, missing target, and unsupported artifact types', () => {
  const transport = loadTransport();
  assert.throws(() => transport.validateRequest(null), /placement request is required/);
  assert.throws(() => transport.validateRequest({}), /placement target is required/);
  const request = validDocsRequest();
  request.target.artifact_type = 'video';
  assert.throws(() => transport.validateRequest(request), /unsupported artifact_type/);
});

test('validateRequest rejects empty required strings', () => {
  const transport = loadTransport();
  const request = validDocsRequest();
  request.target.marker = '   ';
  assert.throws(() => transport.validateRequest(request), /marker is required/);
});

test('place inserts the image at the docs marker index and removes the marker', () => {
  const transport = loadTransport();
  const log = [];
  const result = transport.place(validDocsRequest(), {
    drive: makeDrive(),
    docs: makeDocs(log),
  });
  assert.equal(result.state, 'placed');
  assert.equal(result.asset_id, 'asset-1');
  assert.equal(result.artifact_type, 'docs');
  assert.equal(result.artifact_id, 'doc-1');
  assert.equal(result.marker, '[[IMG]]');
  assert.equal(result.inserted_element_id, 'docs-child-1');
  const insertIndex = log.findIndex(([name]) => name === 'body.insertImage');
  const removeIndex = log.findIndex(([name]) => name === 'marker.removeFromParent');
  assert.ok(insertIndex >= 0, 'image must be inserted');
  assert.ok(removeIndex > insertIndex, 'marker must be removed only after insertion');
  assert.deepEqual(log[insertIndex], ['body.insertImage', 1, { blob: true }]);
  assert.ok(log.some(([name]) => name === 'document.saveAndClose'));
});

test('place fails closed when the docs marker text no longer matches exactly', () => {
  const transport = loadTransport();
  const log = [];
  const children = [
    makeDocsChild('intro paragraph', log),
    makeDocsChild('[[REMOVED]]', log),
    makeDocsChild('closing paragraph', log),
  ];
  const services = {
    drive: makeDrive(),
    docs: {
      openById: () => ({
        getBody: () => makeDocsBody(children, log),
        saveAndClose: () => log.push(['document.saveAndClose']),
      }),
    },
  };
  assert.throws(
    () => transport.place(validDocsRequest(), services),
    /docs target drift: exact marker no longer matches/,
  );
  assert.ok(!log.some(([name]) => name === 'body.insertImage'));
  assert.ok(!log.some(([name]) => name === 'marker.removeFromParent'));
});

test('place fails closed when the docs marker index is invalid', () => {
  const transport = loadTransport();
  const log = [];
  const request = validDocsRequest();
  request.target.index = 5;
  const services = {
    drive: makeDrive(),
    docs: {
      openById: () => ({
        getBody: () => makeDocsBody([
          makeDocsChild('intro paragraph', log),
          makeDocsChild('[[IMG]]', log),
        ], log),
        saveAndClose: () => log.push(['document.saveAndClose']),
      }),
    },
  };
  assert.throws(
    () => transport.place(request, services),
    /docs target drift: marker index is invalid/,
  );
});

test('place applies slides bounds, reports the slide image id, and removes the marker', () => {
  const transport = loadTransport();
  const log = [];
  const request = validDocsRequest();
  request.target.artifact_type = 'slides';
  request.target.bounds = { left: 1, top: 2, width: 3, height: 4 };
  const result = transport.place(request, {
    drive: makeDrive(),
    slides: makeSlides(log),
  });
  assert.equal(result.state, 'placed');
  assert.equal(result.artifact_type, 'slides');
  assert.equal(result.inserted_element_id, 'SLIDE_IMG_1');
  assert.deepEqual(log, [
    ['slide.insertImage', { blob: true }],
    ['image.setLeft', 1],
    ['image.setTop', 2],
    ['image.setWidth', 3],
    ['image.setHeight', 4],
    ['marker.remove'],
  ]);
});

test('place fails closed when the slides target slide is missing', () => {
  const transport = loadTransport();
  const log = [];
  const request = validDocsRequest();
  request.target.artifact_type = 'slides';
  const services = {
    drive: makeDrive(),
    slides: {
      openById: () => ({ getSlideById: () => null }),
    },
  };
  assert.throws(
    () => transport.place(request, services),
    /slides target drift: slide not found/,
  );
});

test('place fails closed when the slides marker element is missing', () => {
  const transport = loadTransport();
  const log = [];
  const request = validDocsRequest();
  request.target.artifact_type = 'slides';
  const markerlessSlide = {
    getPageElementById: () => null,
    insertImage: () => {
      throw new Error('insertImage must not run when the marker is missing');
    },
  };
  const services = {
    drive: makeDrive(),
    slides: {
      openById: () => ({ getSlideById: () => markerlessSlide }),
    },
  };
  assert.throws(
    () => transport.place(request, services),
    /slides target drift: marker element not found/,
  );
});
