import test from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
import * as THREE from "three";

// Mirror Vite's extensionless local TS resolution while exercising real code.
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { updateRecord } = await import("../src/character/ui/history.ts");
const { SpatialPlayer, validateSpatialWindow } = await import("../src/character/spatial.ts");

test("polling updates one turn, and starting another does not rewrite completed history", () => {
  const record = { revision: 0, turns: [] };
  const first = { events: [{ kind: "user_message", sequence: 1, text: "跳舞" }], draft_text: "", route: { engine: "ardy" }, motion_plan: [{ kind: "perform" }], status: "thinking" };
  updateRecord(record, first); updateRecord(record, first);
  assert.equal(record.turns.length, 1);
  const completed = { ...first, status: "waiting", events: [...first.events, { kind: "response_finished", sequence: 2, interrupted: false }, { kind: "interrupted", sequence: 3 }] };
  updateRecord(record, completed);
  assert.equal(record.turns[0].status, "completed");
  updateRecord(record, { ...first, events: [...completed.events, { kind: "user_message", sequence: 4, text: "你好" }], route: { engine: "sentiavatar" }, motion_plan: [], draft_text: "你好呀" });
  assert.equal(record.turns.length, 2);
  assert.equal(record.turns[0].prompt, "跳舞");
  assert.equal(record.turns[0].actions.length, 1);
  assert.equal(record.turns[1].response, "你好呀");
});

function window(index) {
  return { sequence: index, offset: index * .4, seconds: .4, fps: 20, total_seconds: 1.2, hip_height: 1,
    phase_index: index, phase_label: String(index), root: Array.from({ length: 9 }, (_, i) => [index * .4 + i * .05, 1, 0]),
    rotations: { hips: Array.from({ length: 9 }, () => [0, 0, 0, 1]) }, continues: index < 2 };
}

test("spatial program crosses phases on one clock and replays the recording without generation", async () => {
  const scene = new THREE.Object3D(), hips = new THREE.Object3D(); scene.add(hips); hips.position.y = 1;
  let clock = 0, calls = 0, samples = [];
  const player = new SpatialPlayer({ scene, humanoid: { getNormalizedBoneNode: name => name === "hips" ? hips : null }, meta: { metaVersion: "1" } }, () => clock);
  const originalFetch = globalThis.fetch, originalRAF = globalThis.requestAnimationFrame;
  globalThis.fetch = async () => { calls++; return new Response([...Array.from({ length: 3 }, (_, i) => JSON.stringify(window(i))), '{"done":true}', ""].join("\n")); };
  globalThis.requestAnimationFrame = callback => setImmediate(() => { clock += .01; player.update(false); callback(); });
  const packet = { id: "x", session_id: "s", epoch: 1, actions: [{ kind: "perform" }], end_state: "hold" };
  try {
    await player.run(packet, {}, 1, elapsed => samples.push(elapsed));
    assert.equal(calls, 1); assert.equal(player.export().length, 3);
    assert.equal(player.underruns, 0);
    assert.ok(Math.abs(hips.getWorldPosition(new THREE.Vector3()).x - 1.2) < .0001);
    assert.ok(samples.every((v, i) => !i || v >= samples[i - 1]));
    await player.run({ ...packet, preview: true }, {}, 1);
    assert.equal(calls, 1);
  } finally { player.stop(); globalThis.fetch = originalFetch; globalThis.requestAnimationFrame = originalRAF; }
});

test("invalid motion samples never reach the VRM rig", () => {
  const valid = window(0); validateSpatialWindow(valid);
  valid.root[4][1] = NaN;
  assert.throws(() => validateSpatialWindow(valid), /数据无效/);
});
