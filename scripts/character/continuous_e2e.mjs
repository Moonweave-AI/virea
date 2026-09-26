/** Real GPU models: strict clocks, prepared successors, conservation and interruption. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [avatar, output, base = "http://127.0.0.1:8000"] = process.argv.slice(2);
if (!avatar || !output) throw new Error("usage: node continuous_e2e.mjs AVATAR.vrm OUTPUT_DIR [API]");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const report = { started: new Date().toISOString(), errors: [], feedback: [], packets: [] };
page.on("pageerror", error => report.errors.push(String(error)));
page.on("request", request => {
  if (request.method() === "POST" && request.url().endsWith("/feedback")) report.feedback.push({ at: performance.now(), ...request.postDataJSON() });
});
await page.addInitScript(() => {
  window.audioSchedules = [];
  const original = AudioBufferSourceNode.prototype.start;
  AudioBufferSourceNode.prototype.start = function(when, ...args) {
    window.audioSchedules.push({ when, duration: this.buffer?.duration, observedAt: performance.now() });
    return original.call(this, when, ...args);
  };
});
let id;
const state = async () => (await page.request.get(`${base}/api/v1/characters/${id}`)).json();
try {
  await page.goto(`${base}/app/character.html`);
  await page.locator("#avatar").setInputFiles(resolve(avatar));
  const created = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/characters"));
  await page.locator("#start").click();
  id = (await (await created).json()).id;
  const text = "今天我们可以慢慢聊一聊，不用急着把所有事情一次说完。窗外的光线很柔和，让人想停下来休息片刻。你可以先说说今天最在意的一件小事，我会认真听。如果暂时想不到也没关系，我们就一起看看周围，等你准备好了再继续。";
  report.expected_text = text;
  await page.locator("#message").fill(`请逐字说出下面这段话，不要删改或补充，说完等待：${text}`);
  const started = performance.now();
  await page.locator("#send").click();
  await page.waitForFunction(() => document.querySelector("#subtitle").textContent, {}, { timeout: 180_000 });
  report.first_playback_seconds = (performance.now() - started) / 1000;
  await page.waitForFunction(() => Number(document.querySelector("#audio-progress").dataset.seconds) > 0.3);
  await page.locator("#pause").click();
  await page.waitForFunction(() => document.querySelector("#pause").textContent === "继续");
  const clocks = () => page.evaluate(() => ["audio", "motion"].map(name => Number(document.querySelector(`#${name}-progress`).dataset.seconds)));
  const before = await clocks();
  await page.waitForTimeout(400);
  const after = await clocks();
  assert.ok(Math.abs(before[0] - after[0]) < 0.03 && Math.abs(before[1] - after[1]) < 0.03);
  report.pause = { before, after };
  await page.locator("#pause").click();
  let completed;
  for (let index = 0; index < 900; index++) {
    const value = await state();
    if (value.status === "error") throw new Error(JSON.stringify(value.events.at(-1)));
    if (value.buffered) report.lookahead_observed = true;
    if (value.pending && !report.packets.some(p => p.id === value.pending.id)) report.packets.push(value.pending);
    const current = await clocks();
    assert.ok(Math.abs(current[0] - current[1]) < 0.035, "audio and motion share the complete presentation timeline");
    if (value.status === "waiting" && value.history.at(-1)?.role === "assistant") { completed = value; break; }
    await page.waitForTimeout(100);
  }
  assert.ok(completed, "response did not finish");
  report.completed = completed;
  assert.equal(completed.history.at(-1).content, text);
  assert.ok(report.packets.length >= 2 && report.lookahead_observed);
  assert.ok(report.packets.slice(1).every(p => p.motion.native_history_applied));
  assert.ok(report.feedback.every(f => f.status === "completed"));
  report.audio_schedules = await page.evaluate(() => window.audioSchedules);
  report.gaps_seconds = report.audio_schedules.slice(1).map((value, index) => value.when - report.audio_schedules[index].when - report.audio_schedules[index].duration);
  assert.ok(report.gaps_seconds.every(gap => gap >= -0.02 && gap < 0.25), `successor gaps: ${report.gaps_seconds}`);
  await page.screenshot({ path: resolve(output, "complete.png") });
  await page.locator("#message").fill(`请原样说出这段话：${text}`);
  await page.locator("#send").click();
  await page.waitForFunction(() => document.querySelector("#subtitle").textContent, {}, { timeout: 180_000 });
  await page.locator("#interrupt").click();
  const stopped = await state();
  assert.equal(stopped.pending, null); assert.equal(stopped.buffered, null);
  assert.ok(Object.keys(stopped.body.pose).length > 15);
  report.interrupted = stopped;
  await page.locator("#message").fill("请只说：你好，我们接着聊。说完等待。");
  await page.locator("#send").click();
  await page.waitForFunction(() => document.querySelector("#subtitle").textContent, {}, { timeout: 180_000 });
  report.after_interrupt_response = await state();
  assert.ok(report.after_interrupt_response.metrics.motion_seconds < 10, "interruption must preserve a healthy warm worker");
  assert.equal(report.after_interrupt_response.pending.motion.native_history_applied, false, "partial playback is not committed native history");
  await page.locator("#close").click();
  assert.deepEqual(report.errors, []);
  report.outcome = "passed";
} catch (error) {
  report.outcome = "failed"; report.error = String(error); process.exitCode = 1;
  if (id) report.last_state = await state().catch(() => null);
  await page.screenshot({ path: resolve(output, "failure.png") });
} finally {
  if (id) await page.request.delete(`${base}/api/v1/characters/${id}`).catch(() => {});
  await writeFile(resolve(output, "observation.json"), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(JSON.stringify({ outcome: report.outcome, error: report.error, first_playback_seconds: report.first_playback_seconds, gaps: report.gaps_seconds }));
}
