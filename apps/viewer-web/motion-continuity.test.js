import test from "node:test";
import assert from "node:assert/strict";

import {
  clampFrameInsideContinuitySegment,
  continuityBreakFrames,
  continuityMarkers,
  continuityReport,
  continuitySegments,
  frameBlendWithinContinuity,
  resumeFrameAfterContinuityStop,
  segmentForFrame,
} from "./motion-continuity.js";

const report = {
  schema_version: "virea.motion_continuity.v1.0.0",
  status: "discontinuous",
  discontinuity_frames: [142, 208],
};

test("continuity report is resolved from processed preview metadata", () => {
  assert.equal(continuityReport({ metadata: { continuity: report } }), report);
  assert.deepEqual(continuityBreakFrames(report, 300), [142, 208]);
  assert.deepEqual(continuitySegments(report, 300), [
    { start_frame: 0, end_frame: 142, interval: "half_open" },
    { start_frame: 142, end_frame: 208, interval: "half_open" },
    { start_frame: 208, end_frame: 300, interval: "half_open" },
  ]);
});

test("fractional playback cannot interpolate across a discontinuity", () => {
  assert.equal(clampFrameInsideContinuitySegment(report, 300, 141.75), 141);
  assert.deepEqual(frameBlendWithinContinuity(report, 300, 141.75), {
    a: 141,
    b: 141,
    alpha: 0,
    blocked_by_continuity: true,
  });
  assert.deepEqual(frameBlendWithinContinuity(report, 300, 142.25), {
    a: 142,
    b: 143,
    alpha: 0.25,
    blocked_by_continuity: false,
  });
});

test("segment selection treats boundaries as half-open", () => {
  assert.deepEqual(segmentForFrame(report, 300, 141.99), {
    start_frame: 0,
    end_frame: 142,
    interval: "half_open",
  });
  assert.deepEqual(segmentForFrame(report, 300, 142), {
    start_frame: 142,
    end_frame: 208,
    interval: "half_open",
  });
});

test("timeline markers expose every declared break", () => {
  assert.deepEqual(continuityMarkers(report, 300).map(({ frame, ratio }) => [frame, ratio]), [
    [142, 142 / 300],
    [208, 208 / 300],
  ]);
});

test("restarting after an automatic stop jumps exactly to the next segment", () => {
  assert.equal(resumeFrameAfterContinuityStop(report, 300, 142, 141), 142);
  assert.equal(resumeFrameAfterContinuityStop(report, 300, 208, 207), 208);
  assert.equal(resumeFrameAfterContinuityStop(report, 300, 300, 299), 299);
});
