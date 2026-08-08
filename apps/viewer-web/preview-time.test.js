import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  correctedFrameLimitForActualFps,
  explicitFrameLimit,
  maxFramesForPreviewSeconds,
  persistedArtifactFrameLimit,
  previewCoverage,
  previewFpsForSample,
} from "./preview-time.js";

test("time-based preview uses native FPS before the dataset profile fallback", () => {
  assert.equal(previewFpsForSample({ fps: 120, preview_fps_fallback: 60 }), 120);
  assert.equal(previewFpsForSample({ fps: null, preview_fps_fallback: 120 }), 120);
  assert.equal(maxFramesForPreviewSeconds("15", { preview_fps_fallback: 120 }), 1800);
  assert.equal(maxFramesForPreviewSeconds("15", { preview_fps_fallback: 30 }), 450);
  assert.equal(maxFramesForPreviewSeconds("15", { fps: 20 }), 300);
});

test("blank preview seconds preserves the complete-clip API contract", () => {
  assert.equal(maxFramesForPreviewSeconds("", { fps: 120 }), null);
  assert.equal(explicitFrameLimit(""), null);
  assert.equal(explicitFrameLimit("180.9"), 180);
  assert.equal(persistedArtifactFrameLimit(), null);
  assert.throws(() => maxFramesForPreviewSeconds("15", {}), /no native or dataset-profile FPS/);
  assert.throws(() => maxFramesForPreviewSeconds("0", { fps: 30 }), /positive number/);
});

test("fallback FPS is corrected once from the actual preview timebase", () => {
  const croppedAtFallback = {
    fps: 120,
    frame_count: 900,
    sample: {
      metadata: {
        original_time: { fps: 120, frame_count: 2400, duration_sec: 20 },
      },
    },
  };
  assert.equal(correctedFrameLimitForActualFps(15, 900, croppedAtFallback), 1800);
  assert.equal(correctedFrameLimitForActualFps(15, 1800, croppedAtFallback), 1800);

  const lowerActualFps = {
    fps: 30,
    frame_count: 900,
    sample: {
      metadata: {
        original_time: { fps: 30, frame_count: 1800, duration_sec: 60 },
      },
    },
  };
  assert.equal(correctedFrameLimitForActualFps(15, 900, lowerActualFps), 450);

  const completeButTooLong = { fps: 30, frame_count: 600, sample: { metadata: {} } };
  assert.equal(correctedFrameLimitForActualFps(15, 900, completeButTooLong), 450);

  const completeShortClip = { fps: 120, frame_count: 524, sample: { metadata: {} } };
  assert.equal(correctedFrameLimitForActualFps(15, 900, completeShortClip), 900);
});

test("app imports the actual-FPS correction from the module that exports it", async () => {
  const appSource = await readFile(new URL("./app.js", import.meta.url), "utf8");
  const previewTimeImport = appSource.match(/import\s*{([^}]*)}\s*from\s*["']\.\/preview-time\.js["']/s);
  assert.ok(previewTimeImport, "app.js must import preview-time.js");
  assert.match(previewTimeImport[1], /\bcorrectedFrameLimitForActualFps\b/);
  assert.match(previewTimeImport[1], /\bpersistedArtifactFrameLimit\b/);
  const annotationImport = appSource.match(/import\s*{([^}]*)}\s*from\s*["']\.\/annotations\.js["']/s);
  assert.ok(annotationImport, "app.js must import annotations.js");
  assert.doesNotMatch(annotationImport[1], /\bcorrectedFrameLimitForActualFps\b/);
  assert.equal(typeof correctedFrameLimitForActualFps, "function");
});

test("preview coverage distinguishes an explicit crop from a complete clip", () => {
  const crop = previewCoverage({
    fps: 120,
    frame_count: 1800,
    sample: {
      metadata: {
        original_time: { fps: 120, frame_count: 6840, duration_sec: 57 },
      },
    },
  });
  assert.equal(crop.durationSec, 15);
  assert.equal(crop.truncated, true);
  assert.equal(crop.coverageRatio, 15 / 57);

  const complete = previewCoverage({ fps: 20, frame_count: 103, sample: { metadata: {} } });
  assert.equal(complete.durationSec, 5.15);
  assert.equal(complete.truncated, false);
  assert.equal(complete.coverageKnown, false);
  assert.equal(complete.coverageRatio, null);

  const knownComplete = previewCoverage({
    fps: 20,
    frame_count: 103,
    sample: { metadata: { original_time: { fps: 20, frame_count: 103 } } },
  });
  assert.equal(knownComplete.coverageKnown, true);
  assert.equal(knownComplete.truncated, false);
  assert.equal(knownComplete.coverageRatio, 1);
});
