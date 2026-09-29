import test from "node:test";
import assert from "node:assert/strict";
import { PerformanceRecording, mixRecordedAudio } from "../src/character/recording.ts";

const body = x => ({ position: { x, y: 0, z: 0 }, pelvis_height: 1, yaw: 0,
  pose: { hips: [0, 0, 0, 1], head: [0, 0, 0, 1] }, behavior: "speaking", gaze_target: null });

test("a complete performance retains every voice cue and real silent gaps", () => {
  const tape = new PerformanceRecording();
  tape.driver(10, "ardy", "move", "slot1");
  tape.observe(10, body(0), { aa: 0 }, "ardy");
  tape.addSpeech({ id: "first", text: "one", audio_url: "/one", sequence: 0 }, 11, 2);
  tape.addSpeech({ id: "last", text: "two", audio_url: "/two", sequence: 1 }, 14, 1);
  tape.observe(15, body(2), { aa: 1 }, "sentiavatar");
  tape.finish();
  tape.observe(100, body(99), {}, "hold");
  assert.equal(tape.duration, 5);
  assert.deepEqual(tape.speech.map(c => [c.at, c.seconds]), [[1, 2], [4, 1]]);
  assert.equal(tape.sample(2.5).body.position.x, 1);
  const { windows, face } = tape.assets(1);
  assert.equal(windows[0].seconds, 5);
  assert.equal(windows[0].root.length, 101);
  assert.equal(face.values[50][0], .5);
});

test("replay audio uses recorded offsets rather than playing just the last segment", () => {
  const buffer = values => ({ sampleRate: 4, duration: values.length / 4, getChannelData: () => Float32Array.from(values) });
  const context = { sampleRate: 4, createBuffer: (_, length, rate) => {
    const data = new Float32Array(length); return { duration: length / rate, getChannelData: () => data };
  } };
  const audio = mixRecordedAudio(context, 4, [{ at: .5, buffer: buffer([1, 1]) }, { at: 2.5, buffer: buffer([.5, .5]) }]);
  assert.deepEqual([...audio.getChannelData(0)], [0, 0, 1, 1, 0, 0, 0, 0, 0, 0, .5, .5, 0, 0, 0, 0]);
});

test("acknowledged speech retains its decoded buffer after the server removes its URL", () => {
  const tape = new PerformanceRecording(), buffer = { duration: 2 };
  tape.addSpeech({ id: "expired-resource", text: "hello", audio_url: "/already-cleaned-up" }, 3, 2, buffer);
  assert.equal(tape.audioCues()[0].buffer, buffer);
  assert.equal(tape.audioCues()[0].at, 0);
});
