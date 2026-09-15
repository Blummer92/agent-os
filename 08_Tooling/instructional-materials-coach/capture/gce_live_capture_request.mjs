import { invokeGceCapture } from './gce_capture_transport.mjs';
import { runLiveCaptureRequest } from './live_capture_request.mjs';

export async function runGceLiveCaptureRequest({
  request,
  rawRecording,
  browserSessionCapability,
  idempotencyLookup,
  idempotencyRecord,
  invokeCapture = invokeGceCapture,
}) {
  return runLiveCaptureRequest({
    request,
    rawRecording,
    browserSessionCapability,
    invokeCapture,
    ...(idempotencyLookup ? { idempotencyLookup } : {}),
    ...(idempotencyRecord ? { idempotencyRecord } : {}),
  });
}
