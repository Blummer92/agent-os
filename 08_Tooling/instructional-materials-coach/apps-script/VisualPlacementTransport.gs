/**
 * Reference transport for a dedicated reusable-visual placement Apps Script.
 *
 * This file defines the intended runtime seam only. Repository tests must inject
 * fake services; this repository change does not deploy or execute the script.
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
        marker: requireString_(target.marker, 'marker'),
        container_id: requireString_(target.container_id, 'container_id'),
        element_id: requireString_(target.element_id, 'element_id'),
        index: target.index == null ? null : Number(target.index),
        bounds: target.bounds || null
      }
    };
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
      insertedId = image.getObjectId();
      marker.remove();
    } else {
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
      var imageElement = body.insertImage(index, blob);
      insertedId = 'docs-child-' + index;
      markerChild.removeFromParent();
      document.saveAndClose();
    }

    return {
      state: 'placed',
      asset_id: input.asset_id,
      drive_file_id: input.drive_file_id,
      role_id: input.role_id,
      artifact_type: input.target.artifact_type,
      artifact_id: input.target.artifact_id,
      marker: input.target.marker,
      container_id: input.target.container_id,
      inserted_element_id: insertedId
    };
  }

  return { validateRequest: validateRequest_, place: place };
})();
