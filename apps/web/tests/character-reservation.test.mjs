import test from "node:test";
import assert from "node:assert/strict";
import { reservationMatches } from "../src/character/behavior_player.ts";

test("a no-task hold wakes immediately when final settlement becomes available", () => {
  const waiting = { owner: "hold", program_id: null, seconds: 6.4 };
  assert.equal(reservationMatches(waiting, null), true);
  const settlement = { id: "final-rest", status: "settling", actions: [] };
  assert.equal(reservationMatches(waiting, settlement), false);
});

test("response release invalidates its old waiting lease but admits settlement", () => {
  const program = { id: "response", finish_requested: true };
  const old = { owner: "sentiavatar", program_id: "response" };
  assert.equal(reservationMatches(old, program), false);
  assert.equal(reservationMatches({ ...old, settling: true }, program), true);
  assert.equal(reservationMatches({ ...old, settling: true }, { id: "replacement" }), false);
});
