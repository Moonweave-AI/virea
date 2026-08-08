function finiteFrameCount(frameCount) {
  const count = Math.floor(Number(frameCount));
  return Number.isFinite(count) && count > 0 ? count : 0;
}

export function continuityReport(payloadOrReport) {
  if (!payloadOrReport || typeof payloadOrReport !== "object") return null;
  if (payloadOrReport.schema_version === "virea.motion_continuity.v1.0.0") {
    return payloadOrReport;
  }
  const candidates = [
    payloadOrReport.metadata?.continuity,
    payloadOrReport.quality?.continuity,
    payloadOrReport.continuity,
  ];
  return candidates.find((candidate) => candidate && typeof candidate === "object") || null;
}

export function continuityBreakFrames(payloadOrReport, frameCount) {
  const count = finiteFrameCount(frameCount);
  if (!count) return [];
  const report = continuityReport(payloadOrReport);
  const declared = Array.isArray(report?.discontinuity_frames)
    ? report.discontinuity_frames
    : [];
  return [...new Set(declared
    .map((value) => Math.floor(Number(value)))
    .filter((value) => Number.isFinite(value) && value > 0 && value < count))]
    .sort((a, b) => a - b);
}

export function continuitySegments(payloadOrReport, frameCount) {
  const count = finiteFrameCount(frameCount);
  if (!count) return [];
  const boundaries = [0, ...continuityBreakFrames(payloadOrReport, count), count];
  return boundaries.slice(0, -1).map((start, index) => ({
    start_frame: start,
    end_frame: boundaries[index + 1],
    interval: "half_open",
  }));
}

export function segmentForFrame(payloadOrReport, frameCount, frame) {
  const count = finiteFrameCount(frameCount);
  if (!count) return null;
  const value = Math.max(0, Math.min(Number(frame) || 0, count - 1));
  const segments = continuitySegments(payloadOrReport, count);
  return segments.find((segment) => value >= segment.start_frame && value < segment.end_frame)
    || segments.at(-1)
    || null;
}

export function clampFrameInsideContinuitySegment(payloadOrReport, frameCount, frame) {
  const count = finiteFrameCount(frameCount);
  if (!count) return 0;
  const value = Math.max(0, Math.min(Number(frame) || 0, count - 1));
  const segment = segmentForFrame(payloadOrReport, count, value);
  if (!segment) return value;
  // A fractional frame in (end-1, end) would interpolate across the declared
  // discontinuity. Hold the final source sample until playback reaches the
  // next half-open segment exactly; never fabricate an in-between pose.
  return Math.min(value, segment.end_frame - 1);
}

export function frameBlendWithinContinuity(payloadOrReport, frameCount, frame) {
  const count = Math.max(1, finiteFrameCount(frameCount));
  const value = clampFrameInsideContinuitySegment(payloadOrReport, count, frame);
  const a = Math.floor(value);
  const candidate = Math.min(a + 1, count - 1);
  const breaks = continuityBreakFrames(payloadOrReport, count);
  const crossesBoundary = breaks.includes(candidate);
  return {
    a,
    b: crossesBoundary ? a : candidate,
    alpha: crossesBoundary ? 0 : value - a,
    blocked_by_continuity: crossesBoundary,
  };
}

export function continuityMarkers(payloadOrReport, frameCount) {
  const count = finiteFrameCount(frameCount);
  if (!count) return [];
  return continuityBreakFrames(payloadOrReport, count).map((frame) => ({
    frame,
    ratio: frame / count,
    label: `Motion discontinuity before frame ${frame}; playback does not interpolate across this boundary.`,
  }));
}

export function resumeFrameAfterContinuityStop(payloadOrReport, frameCount, resumeFrame, fallbackFrame) {
  const count = finiteFrameCount(frameCount);
  const candidate = Math.floor(Number(resumeFrame));
  if (
    count
    && Number.isFinite(candidate)
    && continuityBreakFrames(payloadOrReport, count).includes(candidate)
  ) {
    return candidate;
  }
  return Math.max(0, Math.min(Number(fallbackFrame) || 0, Math.max(0, count - 1)));
}
