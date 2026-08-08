export const DEFAULT_PREVIEW_SECONDS = 15;

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function previewFpsForSample(sample) {
  return positiveNumber(sample?.fps) ?? positiveNumber(sample?.preview_fps_fallback);
}

export function explicitFrameLimit(value) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const frames = Number(value);
  if (!Number.isFinite(frames) || frames < 1) {
    throw new RangeError("Frame limit must be a positive number");
  }
  return Math.max(1, Math.floor(frames));
}

export function persistedArtifactFrameLimit() {
  // Viewer transport crops are never promoted to formal persisted artifacts.
  return null;
}

export function maxFramesForPreviewSeconds(value, sample) {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new RangeError("Preview seconds must be a positive number or blank for the full clip");
  }
  const fps = previewFpsForSample(sample);
  if (!fps) {
    throw new RangeError("This sample has no native or dataset-profile FPS for a time-based preview");
  }
  return Math.max(1, Math.ceil(seconds * fps - 1e-9));
}

export function previewCoverage(payload) {
  const fps = positiveNumber(payload?.fps);
  const frameCount = positiveNumber(payload?.frame_count) ?? 0;
  const durationSec = fps ? frameCount / fps : positiveNumber(payload?.duration_sec) ?? 0;
  const original = payload?.sample?.metadata?.original_time;
  const originalFps = positiveNumber(original?.fps) ?? fps;
  const originalFrameCount = positiveNumber(original?.frame_count);
  const originalDurationSec = positiveNumber(original?.duration_sec)
    ?? (originalFrameCount && originalFps ? originalFrameCount / originalFps : null);
  const toleranceSec = fps ? 0.5 / fps : 1e-9;
  const coverageKnown = originalDurationSec !== null;
  const truncated = originalDurationSec !== null && originalDurationSec > durationSec + toleranceSec;
  return {
    fps,
    frameCount,
    durationSec,
    originalFrameCount,
    originalDurationSec,
    coverageKnown,
    truncated,
    coverageRatio: coverageKnown && originalDurationSec
      ? Math.min(1, durationSec / originalDurationSec)
      : null,
  };
}

export function correctedFrameLimitForActualFps(secondsValue, currentLimit, payload) {
  const limit = explicitFrameLimit(currentLimit);
  if (limit === null || secondsValue === null || secondsValue === undefined || String(secondsValue).trim() === "") {
    return limit;
  }
  const actualFps = positiveNumber(payload?.fps);
  if (!actualFps) return limit;
  const corrected = Math.max(1, Math.ceil(Number(secondsValue) * actualFps - 1e-9));
  if (!Number.isFinite(corrected) || Math.abs(corrected - limit) <= 1) return limit;
  const coverage = previewCoverage(payload);
  const reachedRequestedBoundary = coverage.frameCount >= limit;
  const requestedSeconds = Number(secondsValue);
  const longerThanRequested = corrected < limit
    && coverage.durationSec > requestedSeconds + (actualFps ? 0.5 / actualFps : 0);
  return coverage.truncated || reachedRequestedBoundary || longerThanRequested ? corrected : limit;
}
