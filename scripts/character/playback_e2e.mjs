/** Real voice-first latency and shared-clock playback controls, using local Chrome. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [avatar, output, base = "http://127.0.0.1:8000"] = process.argv.slice(2);
if (!avatar || !output) throw new Error("usage: node playback_e2e.mjs AVATAR.vrm OUTPUT_DIR [API_URL]");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const report = { started_at: new Date().toISOString(), errors: [], samples: [] };
page.on("pageerror", error => report.errors.push(String(error)));
let id;
try {
  await page.goto(`${base}/app/character.html`);
  await page.locator("#avatar").setInputFiles(resolve(avatar));
  await page.locator("#playback-mode").selectOption("voice_first");
  const created = page.waitForResponse(response => response.request().method() === "POST" && response.url().endsWith("/characters"));
  await page.locator("#start").click();
  id = (await (await created).json()).id;
  await page.locator("#message").fill("只说一句：你好，很高兴见到你。说完请等待。");
  const start = performance.now();
  await page.locator("#send").click();
  await page.waitForFunction(() => document.querySelector("#text-state").textContent === "完整文本已就绪", {}, { timeout: 120_000 });
  report.text_visible_seconds = (performance.now() - start) / 1000;
  await page.waitForFunction(() => Number(document.querySelector("#audio-progress").dataset.seconds) > 0.05, {}, { timeout: 120_000 });
  report.first_playback_seconds = (performance.now() - start) / 1000;
  report.early = await (await page.request.get(`${base}/api/v1/characters/${id}`)).json();
  assert.equal(report.early.latest_expression.motion, null, "Speech starts before motion is ready");
  assert.equal(await page.locator("#subtitle").textContent(), report.early.pending.text);
  await page.screenshot({ path: resolve(output, "voice-first.png") });
  await page.locator("#replay-sync").waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector("#replay-sync").disabled, {}, { timeout: 600_000 });
  report.ready = await (await page.request.get(`${base}/api/v1/characters/${id}`)).json();
  assert.ok(report.ready.latest_expression.motion);
  assert.equal(report.ready.history.filter(item => item.role === "assistant").length, 1, "Do not repeat a completed greeting autonomously");
  await page.locator("#replay-sync").click();
  await page.waitForFunction(() => Number(document.querySelector("#motion-progress").dataset.seconds) > 0.2);
  await page.locator("#pause").click();
  await page.waitForFunction(() => document.querySelector("#pause").textContent === "继续");
  const read = () => page.evaluate(() => ["audio", "motion"].map(name => Number(document.querySelector(`#${name}-progress`).dataset.seconds)));
  const before = await read();
  await new Promise(resolveWait => setTimeout(resolveWait, 500));
  const after = await read();
  assert.ok(Math.abs(before[0] - after[0]) < 0.03 && Math.abs(before[1] - after[1]) < 0.03, "Pause freezes both tracks");
  report.pause = { before, after };
  await page.locator("#pause").click();
  for (let n = 0; n < 6; n++) {
    await new Promise(resolveWait => setTimeout(resolveWait, 80));
    const [audio, motion] = await read();
    report.samples.push({ audio, motion });
    assert.ok(Math.abs(audio - motion) < 0.04, "Both active tracks use the same clock");
  }
  await page.screenshot({ path: resolve(output, "synchronized-replay.png") });
  await page.locator("#interrupt").click();
  await page.waitForFunction(() => document.querySelector("#pause").disabled);
  assert.equal(await page.locator("#subtitle").textContent(), "");
  await page.request.delete(`${base}/api/v1/characters/${id}`);
  await page.waitForFunction(() => document.querySelector("#status").textContent === "会话已结束");
  assert.equal(await page.locator("#start").isEnabled(), true);
  assert.deepEqual(report.errors, []);
  report.outcome = "passed";
} catch (error) {
  report.outcome = "failed"; report.error = String(error); process.exitCode = 1;
  await page.screenshot({ path: resolve(output, "failure.png") });
} finally {
  report.finished_at = new Date().toISOString();
  await writeFile(resolve(output, "observation.json"), JSON.stringify(report, null, 2));
  if (id) await page.request.delete(`${base}/api/v1/characters/${id}`).catch(() => {});
  await browser.close();
  console.log(JSON.stringify({ outcome: report.outcome, error: report.error,
    first_playback_seconds: report.first_playback_seconds, output }));
}
