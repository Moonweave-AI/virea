import type { Performance } from "./contracts";
import { validateSpatialWindow, type SpatialWindow } from "./spatial";

export function speechAt(performance: Performance, seconds: number) {
  return performance.speech.find(clip => seconds >= clip.start_seconds
    && seconds < clip.start_seconds + clip.duration_seconds);
}

export function validatePerformance(performance: Performance, windows: SpatialWindow[]): void {
  if (!Number.isFinite(performance.duration_seconds) || performance.duration_seconds <= 0
    || performance.duration_seconds > 180 || !windows.length) throw new Error("表演时间轴无效");
  let cursor = 0;
  for (const window of windows) {
    validateSpatialWindow(window);
    if (Math.abs(window.offset - cursor) > 1e-6
      || Math.abs(window.total_seconds - performance.duration_seconds) > 1e-6) throw new Error("动作窗口不连续");
    cursor += window.seconds;
  }
  if (Math.abs(cursor - performance.duration_seconds) > 1e-6) throw new Error("动作时间轴提前结束");
  let end = 0;
  for (const clip of [...performance.speech].sort((a, b) => a.start_seconds - b.start_seconds)) {
    if (!Number.isFinite(clip.start_seconds) || !Number.isFinite(clip.duration_seconds)
      || clip.start_seconds < end || clip.duration_seconds <= 0
      || clip.start_seconds + clip.duration_seconds > cursor + 1e-6) throw new Error("语音轨道无效");
    end = clip.start_seconds + clip.duration_seconds;
  }
}
