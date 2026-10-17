/**
 * Reference transport for a dedicated reusable-visual placement Apps Script.
 *
 * This file defines the intended runtime seam only. Repository tests must inject
 * fake services; this repository change does not deploy or execute the script.
 *
 * #3257 hardened contract (reference only, no deployment):
 * - validateRequest_ preserves and enforces the request's artifact revision
 *   identity: a placement request without artifact_revision_id is rejected.
 * - place returns the ACTUAL persisted Docs inline object ID obtained from a
 *   read-back of the persisted document (before/after inline-object diff),
 *   never the pre-repair synthetic `docs-child-<index>`.
 * - place returns verifiable revision evidence: requested_revision_id (as
 *   asked) and post_placement_revision_id (read back after the insertion).
 *
 * The script does NOT enforce live-revision equality against the requested
 * revision: sequential batch insertions legitimately advance the revision
 * between requests, so equality enforcement here would reject genuine
 * batches. Revision continuity across a batch is enforced repository-side
 * by the reconciled batch proof (#3258). Do not claim concurrency safety
 * from revision numbers alone.
 */
var VisualPlacementTransport = (function () {
  'use strict';

  function requireString_(value, name) {
    if (typeof value !== 'string' || value.trim() === '') {
      throw new Error(name + ' is required');
    }
    return value.trim();
  }

  function validateRequest_(request) {
    if (!request || typeof request !== 'object') throw new Error('placement request is required');
    var target = request.target;
    if (!target || typeof target !== 'object') throw new Error('placement target is required');
    var kind = requireString_(target.artifact_type, 'artifact_type');
    if (kind !== 'docs' && kind !== 'slides') throw new Error('unsupported artifact_type');
    return {
      asset_id: requireString_(request.asset_id, 'asset_id'),
      drive_file_id: requireString_(request.drive_file_id, 'drive_file_id'),
      role_id: requireString_(request.role_id, 'role_id'),
      source_plan_id: requireString_(request.source_plan_id, 'source_plan_id'),
      target: {
        artifact_type: kind,
        artifact_id: requireString_(target.artifact_id, 'artifact_id'),
        // #3257: revision identity is preserved and enforced, never dropped.
        artifact_revision_id: requireString_(target.artifact_revision_id, 'artifact_revision_id'),
        marker: requireString_(target.marker, 'marker'),
        container_id: requireString_(target.container_id, 'container_id'),
        element_id: requireString_(target.element_id, 'element_id'),
        index: target.index == null ? null : Number(target.index),
        bounds: target.bounds || null
      }
    };
  }

  /**
   * Read back the persisted Docs state: revision plus inline object ids.
   * Prefers an injected `services.docsReadback(artifactId)` reader (used by
   * conformance tests); falls back to the Advanced Docs service when
   * available in the Apps Script runtime. Fails closed when neither exists
   * rather than synthesizing an element id.
   */
  function readDocsState_(svc, artifactId) {
    if (svc && typeof svc.docsReadback === 'function') {
      return svc.docsReadback(artifactId);
    }
    if (typeof Docs !== 'undefined' && Docs.Documents && typeof Docs.Documents.get === 'function') {
      var resource = Docs.Documents.get(artifactId, {fields: 'revisionId,inlineObjects'});
      var ids = [];
      var inlineObjects = resource.inlineObjects || {};
      for (var id in inlineObjects) {
        if (Object.prototype.hasOwnProperty.call(inlineObjects, id)) ids.push(id);
      }
      return {revisionId: resource.revisionId, inlineObjectIds: ids};
    }
    throw new Error('docs read-back surface is unavailable: cannot verify the persisted inline object id; refusing to synthesize one');
  }

  /**
   * Read back the persisted Slides revision. Prefers an injected
   * `services.slidesReadback(artifactId)` reader; falls back to the
   * Advanced Slides service. Fails closed when neither exists.
   */
  function readSlidesState_(svc, artifactId) {
    if (svc && typeof svc.slidesReadback === 'function') {
      return svc.slidesReadback(artifactId);
    }
    if (typeof Slides !== 'undefined' && Slides.Presentations && typeof Slides.Presentations.get === 'function') {
      var presentation = Slides.Presentations.get(artifactId, {fields: 'revisionId'});
      return {revisionId: presentation.revisionId};
    }
    throw new Error('slides read-back surface is unavailable: cannot verify the persisted revision; refusing to proceed without it');
  }

  function place(request, services) {
    var input = validateRequest_(request);
    var svc = services || {
      drive: DriveApp,
      docs: DocumentApp,
      slides: SlidesApp
    };
    var file = svc.drive.getFileById(input.drive_file_id);
    var blob = file.getBlob();
    var insertedId;
    var postRevisionId;

    if (input.target.artifact_type === 'slides') {
      var presentation = svc.slides.openById(input.target.artifact_id);
      var slide = presentation.getSlideById(input.target.container_id);
      if (!slide) throw new Error('slides target drift: slide not found');
      var marker = slide.getPageElementById(input.target.element_id);
      if (!marker) throw new Error('slides target drift: marker element not found');
      var image = slide.insertImage(blob);
      if (input.target.bounds) {
        if (input.target.bounds.left != null) image.setLeft(Number(input.target.bounds.left));
        if (input.target.bounds.top != null) image.setTop(Number(input.target.bounds.top));
        if (input.target.bounds.width != null) image.setWidth(Number(input.target.bounds.width));
        if (input.target.bounds.height != null) image.setHeight(Number(input.target.bounds.height));
      }
      // Slides insertImage returns the persisted image: its object id is
      // the actual persisted element id.
      insertedId = image.getObjectId();
      marker.remove();
      postRevisionId = readSlidesState_(svc, input.target.artifact_id).revisionId;
    } else {
      // #3257: snapshot the persisted inline objects BEFORE the insertion,
      // then read back AFTER and diff. The single new id is the actual
      // persisted Docs inline object id -- never a synthetic index.
      var before = readDocsState_(svc, input.target.artifact_id);
      var document = svc.docs.openById(input.target.artifact_id);
      var body = document.getBody();
      var index = input.target.index;
      if (!Number.isInteger(index) || index < 0 || index >= body.getNumChildren()) {
        throw new Error('docs target drift: marker index is invalid');
      }
      var markerChild = body.getChild(index);
      if (markerChild.getText() !== input.target.marker) {
        throw new Error('docs target drift: exact marker no longer matches');
      }
      body.insertImage(index, blob);
      markerChild.removeFromParent();
      document.saveAndClose();
      var after = readDocsState_(svc, input.target.artifact_id);
      var newIds = after.inlineObjectIds.filter(function (id) { return before.inlineObjectIds.indexOf(id) === -1; });
      var removedIds = before.inlineObjectIds.filter(function (id) { return after.inlineObjectIds.indexOf(id) === -1; });
      if (newIds.length !== 1 || removedIds.length !== 0) {
        throw new Error('docs insertion verification failed: expected exactly one new inline object, observed new=[' + newIds.join(',') + '] removed=[' + removedIds.join(',') + ']');
      }
      insertedId = newIds[0];
      postRevisionId = after.revisionId;
    }

    if (typeof insertedId !== 'string' || insertedId.trim() === '') {
      throw new Error('placement produced no verifiable inserted element id');
    }
    if (typeof postRevisionId !== 'string' || postRevisionId.trim() === '') {
      throw new Error('placement produced no verifiable post-placement revision');
    }

    return {
      state: 'placed',
      asset_id: input.asset_id,
      drive_file_id: input.drive_file_id,
      role_id: input.role_id,
      artifact_type: input.target.artifact_type,
      artifact_id: input.target.artifact_id,
      requested_revision_id: input.target.artifact_revision_id,
      post_placement_revision_id: postRevisionId,
      marker: input.target.marker,
      container_id: input.target.container_id,
      inserted_element_id: insertedId
    };
  }

  return { validateRequest: validateRequest_, place: place };
})();
