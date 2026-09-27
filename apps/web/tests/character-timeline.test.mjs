import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

// Transpile parameter properties, keeping this pure clock test independent of a browser.
const source = await readFile(new URL("../src/character/timeline.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { ExpressionTimeline } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const packet = sequence => ({ id: String(sequence), stream_id: "one", sequence, offset_seconds: sequence * 2.4 });
function fixture() {
  const sources = [];
  const context = { currentTime: 0, createBufferSource() {
    const value = { connect() {}, disconnect() {}, start(time) { this.time = time; }, stop() { this.stopped = true; } };
    sources.push(value); return value;
  } };
  return { context, sources, timeline: new ExpressionTimeline(context, {}) };
}

test("successors share a gapless clock independent of HTTP feedback", () => {
  const { context, sources, timeline } = fixture(), audio = { duration: 2.4 };
  timeline.register(packet(1), audio);
  timeline.begin(packet(0), audio);
  assert.equal(sources[1].time - sources[0].time, 2.4);
  context.currentTime = 2.8;
  assert.equal(timeline.begin(packet(1), audio).start, sources[1].time);
  assert.equal(timeline.underruns, 0);
});

test("out-of-order decode and late arrival shift unscheduled successors without overlap", () => {
  const { context, sources, timeline } = fixture(), audio = { duration: 2.4 };
  timeline.begin(packet(0), audio);
  timeline.register(packet(2), audio);
  assert.equal(sources.length, 1);
  context.currentTime = 3;
  timeline.register(packet(1), audio);
  assert.equal(sources.length, 3);
  assert.ok(Math.abs(sources[2].time - sources[1].time - 2.4) < 1e-8);
  assert.equal(timeline.underruns, 1);
  timeline.stop();
  assert.ok(sources.every(source => source.stopped));
  const start = timeline.begin({ ...packet(2), stream_id: "new" }, audio).start;
  assert.ok(Math.abs(start - 3.12) < 1e-8);
});
