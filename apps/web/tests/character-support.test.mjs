import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { BodyAuthority } = await import("../src/character/body_authority.ts");
const { GroundSupport } = await import("../src/character/support.ts");
function rig() {
  const scene = new THREE.Object3D(), hips = new THREE.Object3D(), leftFoot = new THREE.Object3D();
  hips.position.y = 1; leftFoot.position.y = -.95; scene.add(hips); hips.add(leftFoot);
  const bones = { hips, leftFoot };
  return { scene, hips, leftFoot, vrm: { scene, humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } } };
}
test("handoff decays an airborne hip offset instead of preserving it forever", () => {
  const { vrm, hips } = rig(), authority = new BodyAuthority(vrm);
  for (let i = 0; i < 60; i++) authority.render("ardy", 1/60, () => { hips.position.y = 1.6; }, true);
  authority.capture(() => { hips.position.y = 1.6; }); // Rotation-only speech carries the held hip height.
  authority.render("sentiavatar", 1/60, () => {}, false);
  assert.ok(Math.abs(hips.position.y - 1.6) < 1e-6);
  for (let i = 0; i < 90; i++) authority.render("sentiavatar", 1/60, () => {}, false);
  assert.ok(Math.abs(authority.groundClearance) < 1e-6);
  assert.ok(Math.abs(hips.position.y - 1) < 1e-6);
});
test("retargeting preserves a real jump and grounded contact at different avatar proportions", () => {
  const { vrm, hips } = rig(), support = new GroundSupport(vrm);
  hips.position.y = 1.4;
  support.align(new Map([["leftFoot", new THREE.Vector3(0, .7, 0)]]));
  assert.ok(Math.abs(support.clearance() - .7) < 1e-6);
  support.align(new Map([["leftFoot", new THREE.Vector3(0, -.02, 0)]]));
  assert.ok(Math.abs(support.clearance()) < 1e-6);
});
