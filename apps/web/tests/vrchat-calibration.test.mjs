import {test} from "node:test";
import assert from "node:assert/strict";
import {calibrationView} from "../src/vrchat-calibration.mjs";

test("progress shows the current server step and remains unchanged while waiting", () => {
  const snapshot = {stage: "verifying", active: true, step: 6, total_steps: 8, percent: 62,
    step_label: "等待游戏确认全身追踪"};
  const result = calibrationView(snapshot);
  assert.equal(result.percent, 62);
  assert.equal(result.count, "[6/8]");
  assert.match(result.label, /游戏/);
  assert.equal(result.complete, false);
  assert.deepEqual(calibrationView(snapshot), result);
});

test("only completed calibration reaches 100 percent", () => {
  assert.equal(calibrationView({stage: "verifying", active: true, percent: 100}).percent, 99);
  const done = calibrationView({stage: "completed", step: 8, total_steps: 8, percent: 100, completed_at: 123});
  assert.equal(done.percent, 100);
  assert.equal(done.count, "[8/8]");
  assert.equal(done.complete, true);
});

test("failure cancellation and connection loss remain visible at the last progress", () => {
  const result = calibrationView({stage: "failed", step: 3, total_steps: 8, percent: 25, error: "未找到校准入口"});
  assert.equal(result.percent, 25);
  assert.equal(result.detail, "未找到校准入口");
  assert.equal(result.failed, true);
  assert.equal(result.active, false);
  assert.match(calibrationView({stage: "cancelled", percent: 25}).title, /已取消/);
  const offline = calibrationView({stage: "aiming", active: true, percent: 37}, true);
  assert.equal(offline.percent, 37);
  assert.match(offline.title, /连接中断/);
  assert.equal(calibrationView(null).visible, false);
});
