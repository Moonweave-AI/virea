import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { BodyAuthority } = await import("../src/character/body_authority.ts");
function rig() {
  const bones = Object.fromEntries(["hips", "leftUpperLeg", "head"].map(name => [name, new THREE.Object3D()]));
  bones.hips.position.y = 1;
  return { bones, owner: new BodyAuthority({ humanoid: { humanBones: bones, getNormalizedBoneNode: n => bones[n] } }) };
}
const rotation = (axis, angle) => new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(...axis), angle);

test("one source owns the whole body including legs, with no additive rotation", () => {
  const { bones, owner } = rig();
  const speech = rotation([1, 0, 0], .7), locomotion = rotation([0, 0, 1], -.9);
  owner.capture(() => { for (const b of Object.values(bones)) b.quaternion.copy(speech); });
  let writes = 0;
  const ardy = () => { writes++; for (const b of Object.values(bones)) b.quaternion.copy(locomotion); };
  for (let i = 0; i < 90; i++) owner.render("ardy", 1 / 60, ardy, true);
  assert.equal(writes, 90);
  assert.ok(bones.head.quaternion.angleTo(locomotion) < 1e-6);
  const boundary = bones.head.quaternion.clone();
  owner.render("sentiavatar", 1 / 60, ardy, true);
  assert.ok(bones.head.quaternion.angleTo(boundary) < 1e-6);
  for (let i = 0; i < 90; i++) owner.render("sentiavatar", 1 / 60, ardy, true);
  assert.equal(writes, 90);
  assert.ok(bones.leftUpperLeg.quaternion.angleTo(speech) < 1e-6);
  assert.ok(bones.head.quaternion.angleTo(speech) < 1e-6);
});

test("silent/unavailable speech holds the actual pose rather than returning to bind pose", () => {
  const { bones, owner } = rig();
  const pose = rotation([0, 1, 0], .6);
  for (let i = 0; i < 90; i++) owner.render("ardy", 1 / 60, () => bones.head.quaternion.copy(pose), true);
  owner.release();
  for (let i = 0; i < 90; i++) owner.render("sentiavatar", 1 / 60, () => assert.fail("inactive model was sampled"), true);
  assert.equal(owner.owner, "hold");
  assert.ok(bones.head.quaternion.angleTo(pose) < 1e-6);
});

test("preparing speech cannot mutate the visible skeleton or root translation", () => {
  const { bones, owner } = rig();
  const held = bones.hips.position.clone();
  owner.capture(() => { bones.hips.position.set(9, 9, 9); bones.head.quaternion.copy(rotation([1, 0, 0], 1)); });
  assert.deepEqual(bones.hips.position.toArray(), held.toArray());
  assert.ok(bones.head.quaternion.angleTo(new THREE.Quaternion()) < 1e-6);
  owner.render("sentiavatar", 1 / 60, () => {}, false);
  assert.deepEqual(bones.hips.position.toArray(), held.toArray());
});
