import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { GroundSupport } = await import("../src/character/support.ts");

test("penetration-only support raises submerged feet and preserves an airborne pose", () => {
  const scene = new THREE.Object3D(), hips = new THREE.Object3D(), foot = new THREE.Object3D();
  scene.add(hips); hips.add(foot); hips.position.y = 1; foot.position.y = -.95;
  const support = new GroundSupport({ scene, humanoid: { getNormalizedBoneNode: name => name === "hips" ? hips : name === "leftFoot" ? foot : null } });
  hips.position.y = .8;
  support.preventPenetration();
  assert.ok(Math.abs(support.clearance()) < 1e-8);
  hips.position.y = 1.3;
  support.preventPenetration();
  assert.ok(Math.abs(hips.position.y - 1.3) < 1e-8, "jump height must remain intact");
});
