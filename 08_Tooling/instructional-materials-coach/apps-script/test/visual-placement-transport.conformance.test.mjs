/**
 * Node conformance tests for the VisualPlacementTransport REFERENCE
 * implementation (#3257, R1 producer repair).
 *
 * This tests the reference Apps Script source with injected fake services
 * only. It is NOT a claim about any deployed Apps Script runtime: Node
 * conformance and deployed-runtime behavior are distinct, and no
 * deployment is performed or authorized here.
 *
 * Run: node --test apps-script/test/visual-placement-transport.conformance.test.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const GS_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  'VisualPlacementTransport.gs',
);

function loadTransport() {
  const code = readFileSync(GS_PATH, 'utf8');
  return vm.runInNewContext(`${code}\nVisualPlacementTransport;`, {});
}

function docsRequest(targetOverrides = {}) {
  return {
    asset_id: 'asset-1',
    drive_file_id: 'file-1',
    role_id: 'figure',
    source_plan_id: 'plan-1',
    content_identity: { sha256: 'abc' },
    target: {
      artifact_type: 'docs',
      artifact_id: 'doc-1',
      artifact_revision_id: 'rev-requested',
      marker: '{{visual:figure}}',
      container_id: 'body',
      element_id: 'body-child-0',
      index: 0,
      bounds: null,
      ...targetOverrides,
    },
  };
}

function fakeDocsServices({
  beforeIds = [],
  afterIds = ['real-object-42'],
  beforeRev = 'rev-before',
  afterRev = 'rev-after',
} = {}) {
  let reads = 0;
  const children = [
    {
      getText: () => '{{visual:figure}}',
      removeFromParent: () => {},
    },
  ];
  const body = {
    getNumChildren: () => children.length,
    getChild: (i) => children[i],
    insertImage: (index) => {
      assert.equal(index, 0);
      return {};
    },
  };
  const document = {
    getBody: () => body,
    saveAndClose: () => {},
  };
  return {
    drive: { getFileById: (id) => ({ getBlob: () => ({ blobFor: id }) }) },
    docs: {
      openById: (id) => {
        assert.equal(id, 'doc-1');
        return document;
      },
    },
    docsReadback: (artifactId) => {
      assert.equal(artifactId, 'doc-1');
      reads += 1;
      return reads === 1
        ? { revisionId: beforeRev, inlineObjectIds: beforeIds }
        : { revisionId: afterRev, inlineObjectIds: afterIds };
    },
  };
}

test('validateRequest preserves the artifact revision identity', () => {
  const t = loadTransport();
  const validated = t.validateRequest(docsRequest());
  assert.equal(validated.target.artifact_revision_id, 'rev-requested');
});

test('validateRequest rejects a request without revision identity', () => {
  const t = loadTransport();
  assert.throws(
    () => t.validateRequest(docsRequest({ artifact_revision_id: '' })),
    /artifact_revision_id is required/,
  );
  const missing = docsRequest();
  delete missing.target.artifact_revision_id;
  assert.throws(() => t.validateRequest(missing), /artifact_revision_id is required/);
});

test('place (docs) returns the actual read-back inline object id, not a synthetic one', () => {
  const t = loadTransport();
  const result = t.place(docsRequest(), fakeDocsServices());
  assert.equal(result.state, 'placed');
  assert.equal(result.inserted_element_id, 'real-object-42');
  assert.ok(
    !/^docs-child-\d+$/.test(result.inserted_element_id),
    'must never return the pre-repair synthetic docs-child-<index> id',
  );
});

test('place (docs) returns requested and post-placement revision evidence', () => {
  const t = loadTransport();
  const result = t.place(docsRequest(), fakeDocsServices());
  assert.equal(result.requested_revision_id, 'rev-requested');
  assert.equal(result.post_placement_revision_id, 'rev-after');
});

test('place (docs) fails closed without a read-back surface instead of synthesizing an id', () => {
  const t = loadTransport();
  const services = fakeDocsServices();
  delete services.docsReadback;
  // No Advanced Docs service exists in Node: the reference must fail
  // closed rather than emit the old synthetic docs-child-<index> id.
  assert.throws(() => t.place(docsRequest(), services), /read-back surface is unavailable/);
});

test('place (docs) fails when the read-back shows no single new inline object', () => {
  const t = loadTransport();
  assert.throws(
    () => t.place(docsRequest(), fakeDocsServices({ afterIds: [] })),
    /expected exactly one new inline object/,
  );
  assert.throws(
    () =>
      t.place(
        docsRequest(),
        fakeDocsServices({ beforeIds: ['old-1'], afterIds: ['old-1', 'new-1', 'new-2'] }),
      ),
    /expected exactly one new inline object/,
  );
});

test('place (slides) returns the persisted image object id and revision evidence', () => {
  const t = loadTransport();
  const image = { getObjectId: () => 'slide-image-7' };
  const slide = {
    getPageElementById: (id) => (id === 'marker-el' ? { remove: () => {} } : null),
    insertImage: () => image,
  };
  const services = {
    drive: { getFileById: () => ({ getBlob: () => ({}) }) },
    slides: {
      openById: (id) => {
        assert.equal(id, 'slides-1');
        return { getSlideById: (sid) => (sid === 'slide-1' ? slide : null) };
      },
    },
    slidesReadback: (artifactId) => {
      assert.equal(artifactId, 'slides-1');
      return { revisionId: 'srev-after' };
    },
  };
  const request = docsRequest({
    artifact_type: 'slides',
    artifact_id: 'slides-1',
    artifact_revision_id: 'srev-requested',
    container_id: 'slide-1',
    element_id: 'marker-el',
    index: null,
  });
  const result = t.place(request, services);
  assert.equal(result.state, 'placed');
  assert.equal(result.inserted_element_id, 'slide-image-7');
  assert.equal(result.requested_revision_id, 'srev-requested');
  assert.equal(result.post_placement_revision_id, 'srev-after');
});
