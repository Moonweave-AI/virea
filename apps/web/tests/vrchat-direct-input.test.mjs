import test from "node:test";
import assert from "node:assert/strict";
import {DirectInput, imageBounds, imagePoint} from "../src/vrchat-direct-input.mjs";

test("coordinates exclude letterboxing, including after changing aspect ratio", () => {
  const rect = {left: 20, top: 40, width: 400, height: 400};
  assert.deepEqual(imageBounds(rect, 1600, 900), {left: 20, top: 127.5, width: 400, height: 225});
  assert.equal(imagePoint(rect, 1600, 900, 220, 100), null);
  assert.deepEqual(imagePoint(rect, 1600, 900, 220, 240), {pointer_x: 0, pointer_y: 0});
  assert.deepEqual(imagePoint(rect, 1600, 900, 420, 352.5), {pointer_x: 1, pointer_y: 1});
  assert.deepEqual(imagePoint(rect, 900, 1600, 107.5, 40), {pointer_x: -1, pointer_y: -1});
  assert.equal(imagePoint(rect, 0, 0, 220, 240), null);
});

test("rapid clicks retain both button edges and their aim positions", () => {
  const input = new DirectInput();
  input.aim({pointer_x: .5, pointer_y: -.5}, 16 / 9);
  input.pointer(true); input.pointer(false);
  input.aim({pointer_x: -.3, pointer_y: .7}, 16 / 9);
  assert.equal(input.next().state.trigger, true);
  const released = input.next();
  assert.equal(released.state.trigger, false);
  assert.equal(released.state.pointer_x, .5);
  assert.equal(input.next().state.pointer_x, -.3);
});

test("opposite movement keys cancel independently; release cancels pending actions", () => {
  const input = new DirectInput();
  input.key("KeyW", true); input.key("KeyS", true);
  assert.equal(input.state.vertical, 0);
  input.key("KeyS", false);
  assert.equal(input.state.vertical, 1);
  for (const code of ["ShiftLeft", "Space", "KeyE", "KeyG", "KeyQ"]) input.key(code, true);
  input.pointer(true); input.release();
  const result = input.next();
  assert.equal(result.command, null);
  for (const key of ["trigger", "run", "jump", "grab", "drop"]) assert.equal(result.state[key], false);
  assert.equal(result.state.vertical, 0);
  assert.equal(input.next().command, null);
});

test("menu shortcuts pulse once, unrelated/chat/mic keys are not intercepted", () => {
  const input = new DirectInput();
  assert.equal(input.key("KeyV", true), false);
  assert.equal(input.key("KeyP", true), false);
  input.key("Escape", true); input.key("Escape", true, true); input.key("Escape", false);
  input.key("Home", true);
  assert.equal(input.next().command, "menu");
  assert.equal(input.next().command, "dashboard");
  assert.equal(input.next().command, null);
  assert.equal(input.key("F8", true), "release");
});

test("look wraps yaw, clamps pitch, keeps pointer stable; recenter is explicit", () => {
  const input = new DirectInput({head_yaw: 170, pointer_x: .6});
  input.look(20, -200);
  assert.equal(input.state.head_yaw, -170);
  assert.equal(input.state.head_pitch, 70);
  assert.equal(input.state.pointer_x, .6);
  input.key("KeyR", true);
  assert.equal(input.state.head_yaw, -170);
  assert.equal(input.state.head_pitch, 0);
  assert.equal(input.state.pointer_x, 0);
});

test("calibration uses deliberate dual trigger, then returns to pointing", () => {
  const input = new DirectInput();
  input.key("KeyT", true); input.key("Enter", true);
  input.aim({pointer_x: 1, pointer_y: 1}, 16 / 9);
  assert.equal(input.state.pointer_x, 0);
  assert.equal(input.next().state.calibration, true);
  assert.equal(input.next().command, "confirm");
  input.key("KeyT", true); input.key("Enter", true);
  input.next();
  assert.equal(input.next().command, "click");
});

test("resume keeps view orientation but never restores held input", () => {
  const input = new DirectInput({head_yaw: 42, head_pitch: -28, trigger: true, vertical: 1});
  assert.equal(input.state.head_yaw, 42);
  assert.equal(input.state.head_pitch, -28);
  assert.equal(input.state.trigger, false);
  assert.equal(input.state.vertical, 0);
});

test("backpressure stops commands instead of replaying an unbounded input history", () => {
  const input = new DirectInput();
  for (let i = 0; i < 32; i++) input.pointer(i % 2 === 0);
  assert.throws(() => input.pointer(true), /延迟/);
  input.release();
  assert.equal(input.next().state.trigger, false);
});
