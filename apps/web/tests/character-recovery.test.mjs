import test from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import * as THREE from "three";
import { rotation, rotationVector } from "../src/character/continuity.ts";

// Vite resolves extensionless TS imports; mirror just that resolution in Node's test runner.
registerHooks({ resolve(specifier, context, next) {
  if (specifier === "./continuity" && context.parentURL?.endsWith("/character/recovery.ts")) {
    return next("./continuity.ts", context);
  }
  return next(specifier, context);
} });
const { PoseRecovery, faceRelease } = await import("../src/character/recovery.ts");

function fixture() {
  const hips = new THREE.Object3D(), arm = new THREE.Object3D();
  const lastQ = rotation(new THREE.Vector3(0.4, -0.2, 1.2));
  const velocity = new THREE.Vector3(0.3, -0.4, 1.1), dt = 1 / 120;
  const sample = (q, position) => ({ rotations: new Map([[arm, q], [hips, rotation(new THREE.Vector3(0, 0.7, 0))]]), position });
  const last = sample(lastQ, new THREE.Vector3(3, 0.95, -2));
  const before = sample(rotation(velocity.clone().multiplyScalar(-dt)).multiply(lastQ), new THREE.Vector3(3, 0.95 - 0.1 * dt, -2));
  const rest = { rotations: new Map([[arm, new THREE.Quaternion()], [hips, new THREE.Quaternion()]]), position: new THREE.Vector3(0, 1, 0) };
  return { hips, arm, lastQ, velocity, recovery: new PoseRecovery(hips, before, last, rest, dt) };
}

test("terminal recovery preserves pose and angular/linear velocity at entry", () => {
  const { hips, arm, lastQ, velocity, recovery } = fixture();
  recovery.apply(0);
  assert.ok(arm.quaternion.angleTo(lastQ) < 1e-6);
  assert.deepEqual(hips.position.toArray(), [3, 0.95, -2]);
  const dt = 1e-5;
  recovery.apply(dt);
  const actual = rotationVector(arm.quaternion.clone().multiply(lastQ.clone().invert())).divideScalar(dt);
  assert.ok(actual.distanceTo(velocity) < 0.003);
  assert.ok(Math.abs((hips.position.y - 0.95) / dt - 0.1) < 0.001);
});

test("recovery ends at rest with zero velocity while retaining ground position and heading", () => {
  const { hips, arm, recovery } = fixture(), dt = 1e-5;
  recovery.apply(recovery.duration - dt);
  const previous = arm.quaternion.clone();
  recovery.apply(recovery.duration);
  assert.ok(arm.quaternion.angleTo(new THREE.Quaternion()) < 1e-6);
  assert.ok(previous.angleTo(arm.quaternion) / dt < 0.005);
  assert.deepEqual(hips.position.toArray(), [3, 1, -2]);
  assert.ok(hips.quaternion.angleTo(rotation(new THREE.Vector3(0, 0.7, 0))) < 1e-6);
});

test("absolute clock sampling is independent of frame order and holds a completed recovery", () => {
  const { hips, arm, recovery } = fixture();
  recovery.apply(0.4); const q = arm.quaternion.clone(), p = hips.position.clone();
  recovery.apply(0.7); recovery.apply(0.4);
  assert.ok(q.angleTo(arm.quaternion) < 1e-6); assert.ok(p.distanceTo(hips.position) < 1e-9);
  recovery.apply(recovery.duration); const end = arm.quaternion.clone();
  recovery.apply(recovery.duration + 10); assert.ok(end.angleTo(arm.quaternion) < 1e-6);
});

test("blink and mouth release before affect, without a one-frame facial reset", () => {
  for (const name of ["blinkLeft", "blinkRight", "aa", "oh", "ou"]) {
    assert.equal(faceRelease(name, 0, 1), 1);
    assert.ok(faceRelease(name, 0.09, 1) > 0 && faceRelease(name, 0.09, 1) < 1);
    assert.equal(faceRelease(name, 0.18, 1), 0);
  }
  assert.ok(faceRelease("happy", 0.18, 1) > 0.8);
  assert.equal(faceRelease("happy", 1, 1), 0);
});
