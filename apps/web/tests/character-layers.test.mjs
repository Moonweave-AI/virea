import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { PoseLayers } = await import("../src/character/pose_layers.ts");

function rig() {
  const bones = Object.fromEntries(["hips", "leftUpperLeg", "rightUpperArm", "head"].map(name => [name, new THREE.Object3D()]));
  bones.hips.position.set(2, 1, 3);
  const layer = new PoseLayers({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] ?? null } });
  return { layer, bones };
}

test("speech residual cannot overwrite locomotion root, hips or legs", () => {
  const { layer, bones } = rig();
  bones.hips.quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), .8);
  bones.leftUpperLeg.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), -.5);
  const hips = bones.hips.quaternion.clone(), leg = bones.leftUpperLeg.quaternion.clone();
  layer.capture(() => {
    for (const b of Object.values(bones)) b.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), .6);
    bones.hips.position.set(0, 0, 0);
  });
  layer.apply(1);
  assert.ok(bones.hips.quaternion.angleTo(hips) < 1e-6);
  assert.ok(bones.leftUpperLeg.quaternion.angleTo(leg) < 1e-6);
  assert.deepEqual(bones.hips.position.toArray(), [2, 1, 3]);
  assert.ok(bones.head.quaternion.angleTo(new THREE.Quaternion()) > .5);
});

test("render sampling never accumulates a speech rotation and release preserves a held task pose", () => {
  const { layer, bones } = rig();
  bones.head.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), .3);
  const base = bones.head.quaternion.clone();
  layer.capture(() => bones.head.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), .5));
  for (let i = 0; i < 100; i++) {
    if (i) layer.restoreBase();
    layer.apply(.016);
    assert.ok(bones.head.quaternion.angleTo(base) <= .501);
  }
  layer.release();
  for (let i = 0; i < 120; i++) { layer.restoreBase(); layer.apply(.016); }
  assert.ok(bones.head.quaternion.angleTo(base) < 1e-5);
});

test("contact ownership excludes the arm while face/head gesture stays available", () => {
  const { layer, bones } = rig();
  layer.capture(() => { bones.rightUpperArm.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), 1); bones.head.quaternion.copy(bones.rightUpperArm.quaternion); });
  layer.apply(1, null, new Set(["rightUpperArm"]));
  assert.ok(bones.rightUpperArm.quaternion.angleTo(new THREE.Quaternion()) < 1e-6);
  assert.ok(bones.head.quaternion.angleTo(new THREE.Quaternion()) > .9);
});
