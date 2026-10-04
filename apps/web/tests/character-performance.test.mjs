import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { SpatialPlayer } = await import("../src/character/spatial.ts");
const { BodyAuthority } = await import("../src/character/body_authority.ts");
const { speechAt, validatePerformance } = await import("../src/character/performance.ts");

const performance = { duration_seconds: 2, speech: [{ id: "a", text: "hello", start_seconds: .5, duration_seconds: .7 }] };
const windows = [0, 1].map(sequence => ({ sequence, offset: sequence, seconds: 1, fps: 30, total_seconds: 2,
  hip_height: 1, phase_kind: "perform", phase_index: sequence, phase_label: String(sequence),
  root: Array.from({ length: 31 }, (_, i) => [sequence + i / 30, 1, 0]),
  rotations: { hips: Array.from({ length: 31 }, () => [0, 0, 0, 1]) }, continues: sequence === 0 }));

test("speech crosses an action boundary and ends before the motion clock", () => {
  validatePerformance(performance, windows);
  assert.equal(speechAt(performance, .49), undefined);
  assert.equal(speechAt(performance, .5).id, "a");
  assert.equal(speechAt(performance, 1.01).id, "a");
  assert.equal(speechAt(performance, 1.2), undefined);
  assert.throws(() => validatePerformance(performance, [windows[0]]), /提前结束/);
  assert.throws(() => validatePerformance({ ...performance, speech: [...performance.speech, { start_seconds: 1, duration_seconds: 1 }] }, windows), /语音轨道无效/);
});

test("a scheduled performance retains one absolute clock through silence, pause and cancellation", async t => {
  const scene = new THREE.Object3D(), hips = new THREE.Object3D(); scene.add(hips); hips.position.y = 1;
  let now = 10, callbacks = [];
  const original = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = fn => callbacks.push(fn);
  t.after(() => { globalThis.requestAnimationFrame = original; });
  const player = new SpatialPlayer({ scene, humanoid: { getNormalizedBoneNode: n => n === "hips" ? hips : null }, meta: { metaVersion: "1" } }, () => now);
  const x = () => hips.getWorldPosition(new THREE.Vector3()).x;
  const tick = async time => { now = time; const due = callbacks; callbacks = []; due.forEach(fn => fn()); await new Promise(setImmediate); player.update(false); };
  const run = player.run({ id: "x", temporal: true, spatial_windows: windows, end_state: "hold" }, {}, 1, () => {}, null, 11);
  await tick(10.5); assert.equal(x(), 0);
  await tick(11.7); assert.ok(Math.abs(x() - .7) < 1e-5);
  await tick(11.7); assert.ok(Math.abs(x() - .7) < 1e-5, "suspended AudioContext cannot advance body");
  await tick(12.6); assert.ok(Math.abs(x() - 1.6) < 1e-5, "body continues after the last voice ends");
  await tick(13); await run;
  assert.ok(Math.abs(x() - 2) < 1e-5);
  const next = player.run({ id: "y", temporal: true, spatial_windows: windows, end_state: "hold" }, {}, 1);
  const rejected = assert.rejects(next, /Interrupted/); player.stop(); await tick(13.1); await rejected;
});

for (const backend of ["motioncraft", "syntalker"]) test(`${backend} exclusively owns all body bones`, () => {
  const bones = Object.fromEntries(["hips", "head", "leftUpperLeg"].map(n => [n, new THREE.Object3D()]));
  const authority = new BodyAuthority({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } });
  const target = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), .4);
  for (let i = 0; i < 90; i++) authority.render(backend, 1 / 60, () => Object.values(bones).forEach(b => b.quaternion.copy(target)), true);
  assert.equal(authority.owner, backend);
  for (const bone of Object.values(bones)) assert.ok(bone.quaternion.angleTo(target) < 1e-6);
});
