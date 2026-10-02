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

test("terminal activity release admits companion expression but cannot revive canceled activity", () => {
  const companion = { owner: "sentiavatar", program_id: "task", advances_activity: false };
  for (const status of ["completed", "failed", "interrupted"]) {
    const program = { id: "task", status, finish_requested: true };
    assert.equal(reservationMatches(companion, program), true);
    assert.equal(reservationMatches({ ...companion, advances_activity: true }, program), false);
  }
  assert.equal(reservationMatches(companion, { id: "task", status: "settling", finish_requested: true }), false);
});
