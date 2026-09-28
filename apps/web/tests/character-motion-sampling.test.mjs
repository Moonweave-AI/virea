import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
import { samplePosition, sampleRotation } from "../src/character/motion_sampling.ts";

registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { validateSpatialWindow } = await import("../src/character/spatial.ts");

test("adjacent native windows have matching position and angular velocity", () => {
  const positions = Array.from({ length: 7 }, (_, i) => [Math.sin(i * .25), i * .1, 0]);
  const rotations = Array.from({ length: 7 }, (_, i) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), i * i * .025).toArray());
  const a = positions.slice(0, 4), b = positions.slice(3);
  const ra = rotations.slice(0, 4), rb = rotations.slice(3);
  const dt = 1e-4;
  const boundary = samplePosition(a, 3, undefined, b);
  const left = boundary.clone().sub(samplePosition(a, 3 - dt, undefined, b)).divideScalar(dt);
  const right = samplePosition(b, dt, a).sub(boundary).divideScalar(dt);
  assert.ok(left.distanceTo(right) < .001);
  const q = sampleRotation(ra, 3, undefined, rb);
  assert.ok(q.angleTo(sampleRotation(rb, 0, ra)) < 1e-7);
  const vl = q.angleTo(sampleRotation(ra, 3 - dt, undefined, rb)) / dt;
  const vr = q.angleTo(sampleRotation(rb, dt, ra)) / dt;
  assert.ok(Math.abs(vl - vr) < .001);
});

test("quaternion sign flips preserve rotations and all native samples", () => {
  const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), .7);
  const values = [q.toArray(), q.toArray().map(x => -x), q.toArray()];
  for (const t of [0, .1, .5, 1, 1.9, 2]) assert.ok(sampleRotation(values, t).angleTo(q) < 1e-7);
});

test("window validation follows advertised frame timing, including short terminal windows", () => {
  for (const frames of [8, 40, 12]) {
    const window = { root: Array.from({ length: frames + 1 }, () => [0, 1, 0]),
      rotations: { hips: Array.from({ length: frames + 1 }, () => [0, 0, 0, 1]) },
      seconds: frames / 20, fps: 20, offset: 0, total_seconds: 30 };
    assert.doesNotThrow(() => validateSpatialWindow(window));
    assert.throws(() => validateSpatialWindow({ ...window, seconds: .123 }));
  }
});
