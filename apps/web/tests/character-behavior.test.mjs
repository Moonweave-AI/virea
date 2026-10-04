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

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const turn = () => new Promise(setImmediate);

test("a ready successor plays without waiting for receipts; server order and captured clocks are preserved", async t => {
  const finished = [deferred(), deferred()], acknowledgement = deferred(), buffered = deferred();
  const receipts = [], played = [];
  let clock = 0, plans = 0, needed = true;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    const body = JSON.parse(init.body);
    if (url.endsWith("/feedback")) {
      receipts.push({ id: url.split("/").at(-2), ...body });
      if (body.status === "completed" && url.includes("/1/")) await acknowledgement.promise;
      return Response.json({ accepted: true });
    }
    if (url.endsWith("/motion")) return Response.json({ windows: [] });
    return Response.json({ id: String(++plans), after: body.after, owner: "ardy", seconds: 1, terminal: plans === 2 });
  });
  const player = new BehaviorPlayer({ state: () => ({ time: clock }), speech: () => ({ clock_seconds: clock }),
    hipHeight: () => 1, needed: () => needed, canStart: () => true, report: () => {},
    buffer: () => buffered.resolve(), play: async ({ slot }) => {
      played.push({ id: slot.id, clock }); await finished[Number(slot.id) - 1].promise;
    } });
  const run = player.run("session");
  await buffered.promise;
  clock = 1; finished[0].resolve(); await turn();
  assert.deepEqual(played, [{ id: "1", clock: 0 }, { id: "2", clock: 1 }]);
  assert.deepEqual(receipts.map(r => r.status), ["playing", "completed"]);
  clock = 2; needed = false; finished[1].resolve(); await turn();
  clock = 10; acknowledgement.resolve(); await run;
  assert.deepEqual(receipts.map(r => [r.id, r.status, r.clock_seconds, r.body.time]), [
    ["1", "playing", 0, 0], ["1", "completed", 1, 1], ["2", "playing", 1, 1], ["2", "completed", 2, 2],
  ]);
});

test("a rejected asynchronous receipt cancels the renderer and surfaces the failure", async t => {
  const first = deferred(), second = deferred(), buffered = deferred();
  let plans = 0, cancels = 0;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.endsWith("/feedback")) {
      if (url.includes("/1/") && JSON.parse(init.body).status === "completed") return new Response("offline", { status: 503 });
      return Response.json({ accepted: true });
    }
    if (url.endsWith("/motion")) return Response.json({ windows: [] });
    return Response.json({ id: String(++plans), owner: "ardy", seconds: 1, terminal: plans === 2 });
  });
  const player = new BehaviorPlayer({ state: () => ({}), speech: () => ({}), hipHeight: () => 1,
    needed: () => true, canStart: () => true, report: () => {}, buffer: () => buffered.resolve(),
    cancel: () => { cancels++; second.resolve(); },
    play: ({ slot }) => slot.id === "1" ? first.promise : second.promise });
  const run = player.run("session");
  const rejected = assert.rejects(run, /503.*offline/);
  await buffered.promise; first.resolve(); await rejected;
  assert.ok(cancels > 0); assert.equal(player.running, false);
});

test("a late aborted receipt cannot stop a replacement playback", async t => {
  const pending = deferred(); let cancels = 0;
  t.mock.method(globalThis, "fetch", async url => {
    if (url.endsWith("/feedback")) { await pending.promise; throw new DOMException("Interrupted", "AbortError"); }
    return Response.json({ id: "old", owner: "hold", speech_available: false });
  });
  const player = new BehaviorPlayer({ state: () => ({}), speech: () => ({ available: false }), hipHeight: () => 1,
    needed: () => true, canStart: () => true, report: () => {}, play: async () => {}, cancel: () => { cancels++; } });
  const run = player.run("session");
  const rejected = assert.rejects(run, /Interrupted/);
  await turn(); player.stop(); const atStop = cancels;
  pending.resolve(); await rejected;
  assert.equal(cancels, atStop);
});

test("a rejected ownership receipt stops instead of retrying the broken receipt chain", async t => {
  let played = false, plans = 0;
  t.mock.method(globalThis, "fetch", async url => {
    if (url.endsWith("/feedback")) return new Response("stale", { status: 409 });
    plans++; return Response.json({ id: "stale", owner: "hold", speech_available: false });
  });
  const player = new BehaviorPlayer({ state: () => ({}), speech: () => ({ available: false }), hipHeight: () => 1,
    needed: () => true, canStart: () => true, report: () => {}, play: async () => { played = true; } });
  await assert.rejects(player.run("session"));
  assert.equal(played, false); assert.equal(plans, 1); assert.equal(player.running, false);
});
