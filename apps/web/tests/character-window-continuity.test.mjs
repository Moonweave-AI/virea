import test from "node:test";
import assert from "node:assert/strict";
import * as THREE from "three";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { SpatialPlayer } = await import("../src/character/spatial.ts");

const window = (start, offset = 0, total = .4) => ({ offset, seconds: .4, fps: 20, total_seconds: total,
  root: Array.from({ length: 9 }, (_, i) => [start + i / 20, 1, 0]),
  rotations: { hips: Array.from({ length: 9 }, (_, i) => new THREE.Quaternion()
    .setFromAxisAngle(new THREE.Vector3(0, 1, 0), start + i / 20).toArray()) },
});
function fixture(t) {
  const scene = new THREE.Object3D(), hips = new THREE.Object3D(); scene.add(hips);
  let clock = 0, callbacks = [];
  const original = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = callback => { callbacks.push(callback); };
  t.after(() => { globalThis.requestAnimationFrame = original; });
  const player = new SpatialPlayer({ scene, humanoid: { getNormalizedBoneNode: name => name === "hips" ? hips : null },
    meta: { metaVersion: "1" } }, () => clock);
  return { player, hips, set: value => { clock = value; },
    tick: async value => { clock = value; const due = callbacks; callbacks = []; due.forEach(fn => fn()); await new Promise(setImmediate); },
    play: (id, windows, after = null) => player.run({ id, temporal: true, spatial_windows: windows, end_state: "hold" }, {}, 1, () => {}, after),
    x: () => { player.update(false); return hips.getWorldPosition(new THREE.Vector3()).x; } };
}

test("rendering samples the next native window before the async pump's RAF callback", async t => {
  const f = fixture(t), run = f.play("a", [window(0, 0, .8), window(.4, .4, .8)]);
  f.set(.413); assert.ok(Math.abs(f.x() - .413) < 1e-6);
  await f.tick(.8); await run;
});

test("buffered reservations preserve clock overshoot and both boundary derivatives", async t => {
  const f = fixture(t), a = f.play("a", [window(0)]);
  f.player.buffer("a", "b", [window(.4)]);
  f.set(.399); assert.ok(Math.abs(f.x() - .399) < 1e-6);
  await f.tick(.413); await a;
  const b = f.play("b", [window(.4)], "a");
  assert.ok(Math.abs(f.x() - .413) < 1e-6, "time between frames must not reset to the endpoint");
  assert.ok(Math.abs(f.hips.quaternion.angleTo(new THREE.Quaternion()) - .413) < 1e-6);
  await f.tick(.8); await b;
});

test("a late successor starts at its beginning and interruption discards old lookahead", async t => {
  const f = fixture(t), a = f.play("a", [window(0)]);
  await f.tick(.41); await a;
  f.set(1); f.player.buffer("a", "b", [window(.4)]);
  const b = f.play("b", [window(.4)], "a");
  assert.ok(Math.abs(f.x() - .4) < 1e-6, "a real underrun must not skip unseen motion");
  f.player.buffer("b", "c", [window(.8)]);
  const rejected = assert.rejects(b, /Interrupted/); f.player.stop(); await f.tick(1.1); await rejected;
  const c = f.play("c", [window(.8)], "b");
  assert.ok(Math.abs(f.x() - .8) < 1e-6);
  await f.tick(1.51); await c;
});

test("a scheduled cross-model boundary keeps its explicit start instead of skipping the bridge", async t => {
  const f = fixture(t), a = f.play("a", [window(0)]);
  f.player.buffer("a", "bridge", [window(.4)], 1);
  await f.tick(.41); await a;
  f.set(1.013);
  const b = f.play("bridge", [window(.4)], "a");
  assert.ok(Math.abs(f.x() - .413) < 1e-6);
  await f.tick(1.41); await b;
});
