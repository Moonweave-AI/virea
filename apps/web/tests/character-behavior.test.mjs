import test from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { BehaviorPlayer } = await import("../src/character/behavior_player.ts");

test("a playback failure releases its exclusive reservation", async t => {
  const receipts = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    const body = JSON.parse(init.body);
    if (url.endsWith("/feedback")) { receipts.push(body.status); return Response.json({ accepted: true }); }
    return Response.json({ id: "slot", owner: "sentiavatar", seconds: 1, speech_available: true });
  });
  const player = new BehaviorPlayer({ state: () => ({}), speech: () => ({ available: true }),
    hipHeight: () => 1, needed: () => true, canStart: () => true, report: () => {},
    play: async () => { throw new Error("renderer failed"); } });
  await assert.rejects(player.run("session"), /renderer failed/);
  assert.deepEqual(receipts, ["playing", "failed"]);
  assert.equal(player.running, false);
  assert.equal(player.owner, "hold");
});

test("joint performances prepare motion before waiting for audible speech", async t => {
  let voiceReady = false, needed = true, prepared = false, plans = 0;
  const receipts = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.endsWith("/motion")) { prepared = true; return Response.json({ windows: [] }); }
    if (url.endsWith("/feedback")) { receipts.push(JSON.parse(init.body).status); return Response.json({ accepted: true }); }
    return Response.json({ id: String(++plans), owner: "ardy", seconds: 1 });
  });
  const original = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = callback => setImmediate(callback);
  t.after(() => { globalThis.requestAnimationFrame = original; });
  const player = new BehaviorPlayer({ state: () => ({}), speech: () => ({ available: voiceReady }),
    hipHeight: () => 1, needed: () => needed, canStart: () => voiceReady, report: () => {},
    play: async () => { needed = false; } });
  const run = player.run("session");
  await new Promise(setImmediate);
  assert.equal(prepared, true);
  assert.deepEqual(receipts, []);
  voiceReady = true;
  await run;
  assert.deepEqual(receipts, ["playing", "completed", "interrupted"]);
});
