import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { RotationBridge, rotation, rotationVector } from "../src/character/continuity.ts";

test("a bridge preserves executed pose and settles onto the new clip", () => {
  const held = rotation(new THREE.Vector3(0, 0, 1));
  const incoming = rotation(new THREE.Vector3(0, 0, -0.3));
  const bridge = new RotationBridge(held, incoming);
  const start = incoming.clone(); bridge.apply(start, 0);
  assert.ok(start.angleTo(held) < 1e-6);
  const end = incoming.clone(); bridge.apply(end, bridge.duration);
  assert.ok(end.angleTo(incoming) < 1e-6);
  const beforeEnd = incoming.clone(); bridge.apply(beforeEnd, bridge.duration - 1e-4);
  assert.ok(beforeEnd.angleTo(end) / 1e-4 < 0.01);
});

test("same-axis motion enters with executed angular velocity without a pose reset", () => {
  const held = rotation(new THREE.Vector3(0, 0, 0.7));
  const first = rotation(new THREE.Vector3(0, 0, -0.5));
  const bridge = new RotationBridge(held, first, new THREE.Vector3(0, 0, 0.5), new THREE.Vector3(0, 0, 1));
  const dt = 1e-5;
  const sampled = rotation(new THREE.Vector3(0, 0, -0.5 + dt));
  bridge.apply(sampled, dt);
  const velocity = rotationVector(sampled.multiply(held.clone().invert())).z / dt;
  assert.ok(Math.abs(velocity - 0.5) < 0.01);
});

test("quaternion sign changes do not create a full revolution", () => {
  const q = rotation(new THREE.Vector3(0.2, -0.3, 0.6));
  const opposite = new THREE.Quaternion(-q.x, -q.y, -q.z, -q.w);
  const bridge = new RotationBridge(q, opposite);
  bridge.apply(opposite, 0.1);
  assert.ok(opposite.angleTo(q) < 1e-6);
});

test("a change of rotation axis preserves the measured angular velocity", () => {
  const held = rotation(new THREE.Vector3(0.5, -0.2, 0.3));
  const first = rotation(new THREE.Vector3(-0.2, 0.4, -0.1));
  const heldVelocity = new THREE.Vector3(0.3, -0.1, 0.2);
  const incomingVelocity = new THREE.Vector3(-0.1, 0.2, 0.3);
  const bridge = new RotationBridge(held, first, heldVelocity, incomingVelocity);
  const dt = 1e-5;
  const sampled = rotation(incomingVelocity.clone().multiplyScalar(dt)).multiply(first);
  bridge.apply(sampled, dt);
  const velocity = rotationVector(sampled.multiply(held.clone().invert())).divideScalar(dt);
  assert.ok(velocity.distanceTo(heldVelocity) < 0.002);
});
