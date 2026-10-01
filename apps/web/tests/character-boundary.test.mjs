import test from "node:test";
import assert from "node:assert/strict";
import { registerHooks } from "node:module";
registerHooks({ resolve(specifier, context, next) {
  try { return next(specifier, context); }
  catch (error) { if (specifier.startsWith(".")) return next(specifier + ".ts", context); throw error; }
} });
const { boundaryExpired, boundaryReady } = await import("../src/character/behavior_player.ts");

test("native body handoffs reject expired audible targets, including generation stalls", () => {
  const slot = { seconds: 2, boundary_clock: 10, boundary_frame_seconds: .05 };
  assert.equal(boundaryExpired(slot, 8.01), false);
  assert.equal(boundaryExpired(slot, 9), true);
  assert.equal(boundaryExpired({ seconds: 2 }, 99), false);
});

test("early native results wait for their scheduled audio boundary", () => {
  const slot = { seconds: 2, boundary_clock: 10, boundary_frame_seconds: .05 };
  assert.equal(boundaryReady(slot, 7), false);
  assert.equal(boundaryReady(slot, 8), true);
  assert.equal(boundaryReady({ seconds: 2 }, 7), true);
});
