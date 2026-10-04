import test from "node:test";
import assert from "node:assert/strict";
import { SpeechClock, cueReached } from "../src/character/speech_clock.ts";

const packet = (id, epoch, marks) => ({ id, epoch, text: id, speech_marks: marks.map(([name, offset_seconds]) => ({ name, offset_seconds })) });

test("audible events are separate from generation and optional motion readiness", () => {
  const clock = new SpeechClock();
  clock.begin(packet("a", 1, [["reply:start", 0], ["utterance:0:end", 1.25]]), 10, 2.4);
  assert.equal(clock.observe(9, true).active, false);
  assert.deepEqual(clock.observe(9, true).marks, {});
  assert.equal(clock.observe(11, false).active, true);
  assert.equal(clock.observe(11, false).available, false);
  assert.equal(cueReached({ event: "utterance_end", utterance: 0 }, 1, clock.observe(11, true)), false);
  assert.equal(cueReached({ event: "utterance_end", utterance: 0 }, 1, clock.observe(11.25, false)), true);
});

test("pause does not advance events; a new packet keeps earlier cue receipts", () => {
  const clock = new SpeechClock();
  clock.begin(packet("a", 1, [["reply:start", 0], ["utterance:0:end", 1]]), 1, 2);
  const paused = clock.observe(1.5, true);
  assert.deepEqual(clock.observe(1.5, true), paused);
  clock.begin(packet("b", 1, [["reply:end", 2]]), 3, 2);
  assert.deepEqual(clock.observe(5, false).marks, { "reply:start": 1, "utterance:0:end": 2, "reply:end": 5 });
  assert.equal(clock.observe(5, false).active, false);
});

test("interruption invalidates scheduled but inaudible markers", () => {
  const clock = new SpeechClock();
  clock.begin(packet("a", 1, [["reply:end", 4]]), 10, 4);
  clock.reset();
  assert.deepEqual(clock.observe(100, true).marks, {});
  clock.begin(packet("b", 2, [["reply:start", 0]]), 101, 2);
  assert.equal(cueReached({ event: "reply_start", utterance: null }, 1, clock.observe(102, true)), false);
});
