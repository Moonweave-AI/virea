import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { contactIK } from "../src/character/interaction.ts";

test("contact correction reaches a nearby target without moving the body root", () => {
  const root = new THREE.Object3D(), arm = new THREE.Object3D(), elbow = new THREE.Object3D(), hand = new THREE.Object3D();
  root.add(arm); arm.add(elbow); elbow.add(hand);
  elbow.position.x = .3; hand.position.x = .3;
  const target = new THREE.Vector3(.35, .3, .1);
  for (let i = 0; i < 5; i++) contactIK([elbow, arm], hand, target, 1);
  assert.ok(hand.getWorldPosition(new THREE.Vector3()).distanceTo(target) < .002);
  assert.deepEqual(root.position.toArray(), [0, 0, 0]);
  assert.ok(Math.abs(arm.quaternion.length() - 1) < 1e-6);
});

test("unreachable contacts report error rather than translating the character", () => {
  const root = new THREE.Object3D(), arm = new THREE.Object3D(), hand = new THREE.Object3D();
  root.add(arm); arm.add(hand); hand.position.x = .4;
  assert.ok(contactIK([arm], hand, new THREE.Vector3(5, 0, 0), 1) > 4);
  assert.deepEqual(root.position.toArray(), [0, 0, 0]);
});
