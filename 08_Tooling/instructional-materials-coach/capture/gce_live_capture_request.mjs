import { invokeGceCapture } from './gce_capture_transport.mjs';
import { runLiveCaptureRequest } from './live_capture_request.mjs';

export async function runGceLiveCaptureRequest({
  request,
  rawRecording,
  browserSessionCapability,
  fileInputArtifacts = [],
  idempotencyLookup,
  idempotencyRecord,
  invokeCapture = invokeGceCapture,
}) {
  return runLiveCaptureRequest({
    request,
    rawRecording,
    browserSessionCapability,
    fileInputArtifacts,
    invokeCapture,
    ...(idempotencyLookup ? { idempotencyLookup } : {}),
    ...(idempotencyRecord ? { idempotencyRecord } : {}),
  });
}

export async function runGceLiveCaptureWithEvidence({
  request,
  rawRecording,
  browserSessionCapability,
  fileInputArtifacts = [],
  idempotencyLookup,
  idempotencyRecord,
  invokeCapture = invokeGceCapture,
}) {
  let transportEvidence = null;
  const receipt = await runLiveCaptureRequest({
    request,
    rawRecording,
    browserSessionCapability,
    fileInputArtifacts,
    invokeCapture: async (payload) => {
      transportEvidence = await invokeCapture(payload);
      return transportEvidence;
    },
    ...(idempotencyLookup ? { idempotencyLookup } : {}),
    ...(idempotencyRecord ? { idempotencyRecord } : {}),
  });

  const validCapture = receipt.capture_status === 'valid'
    && transportEvidence?.capture_result?.status === 'valid';
  const screenshots = validCapture && Array.isArray(transportEvidence?.screenshots)
    ? Object.freeze(transportEvidence.screenshots.map((item) => Object.freeze(structuredClone(item))))
    : Object.freeze([]);

  return Object.freeze({
    receipt,
    capture_result: transportEvidence?.capture_result ?? null,
    screenshots,
    authentication_status: transportEvidence?.capture_result?.authentication_status ?? receipt.authentication_status ?? null,
    sensitive_evidence: screenshots.length > 0,
    persisted_evidence: false,
  });
}
