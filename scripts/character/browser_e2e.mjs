/** Real-model browser observation. Requires a running API, Qwen, Kokoro and READY SentiAvatar. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { chromium } from "playwright";

const [avatar, output, base = "http://127.0.0.1:8000"] = process.argv.slice(2);
if (!avatar || !output) throw new Error("usage: node browser_e2e.mjs AVATAR.vrm OUTPUT_DIR [API_URL]");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.VIREA_E2E_BROWSER_PATH,
  channel: process.env.VIREA_E2E_BROWSER_PATH ? undefined : "chrome",
  args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [], samples = [];
const run = promisify(execFile);
let sessionId = null;
let screenshotTaken = false;
page.on("pageerror", error => errors.push(String(error)));
const report = { schema_version: "virea.character_browser_observation.v1", started_at: new Date().toISOString(), samples, errors };
try {
  await page.goto(`${base}/app/character.html`);
  await page.locator("#avatar").setInputFiles(resolve(avatar));
  await page.locator("#playback-mode").selectOption("synchronized");
  await page.locator("#start").click({ timeout: 30_000 });
  await page.locator("#send").waitFor({ state: "visible" });
  // Derive the active session from the browser's regular polling response.
  const pollResponse = await page.waitForResponse(response => /\/characters\/[a-f0-9]{32}$/.test(response.url()), { timeout: 20_000 });
  sessionId = (await pollResponse.json()).id;
  report.session_id = sessionId;
  report.webgl = await page.locator("canvas").evaluate(canvas => {
    const gl = canvas.getContext("webgl2");
    const extension = gl.getExtension("WEBGL_debug_renderer_info");
    return { renderer: gl.getParameter(extension ? extension.UNMASKED_RENDERER_WEBGL : gl.RENDERER) };
  });
  await page.locator("#message").fill("只说一句：你好，很高兴见到你。说完请等待。");
  const started = Date.now();
  await page.locator("#send").click();
  let completed = null;
  for (let attempt = 0; attempt < 900; attempt++) {
    const response = await page.request.get(`${base}/api/v1/characters/${sessionId}`);
    const state = await response.json();
    let gpu = null;
    try { gpu = (await run("nvidia-smi", ["--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"])).stdout.trim(); } catch {}
    samples.push({ seconds: (Date.now() - started) / 1000, status: state.status, gpu, metrics: state.metrics });
    if (state.status === "error") throw new Error(JSON.stringify(state.events.at(-1)));
    if (!screenshotTaken && await page.locator("#subtitle").textContent()) {
      await page.screenshot({ path: resolve(output, "speaking.png") });
      screenshotTaken = true;
    }
    const ack = state.events.find(event => event.kind === "playback_feedback");
    if (ack) {
      assert.equal(ack.feedback.status, "completed", JSON.stringify(ack));
      completed = state;
      break;
    }
    await new Promise(resolveWait => setTimeout(resolveWait, 1000));
  }
  assert.ok(completed, "No complete expression within the inference budget");
  report.first_response = completed;
  assert.ok(Object.keys(completed.body.pose).length > 15, "Executed pose must contain real humanoid bones");
  await page.locator("#message").fill("请只说：我会继续留在这里，和你一起看看周围的世界。说完请等待。");
  await page.locator("#send").click();
  await page.waitForFunction(() => Boolean(document.querySelector("#subtitle")?.textContent), { }, { timeout: 600_000 });
  await new Promise(resolveWait => setTimeout(resolveWait, 300));
  const active = await (await page.request.get(`${base}/api/v1/characters/${sessionId}`)).json();
  assert.equal(active.status, "awaiting_playback", "Second turn must reach active playback");
  assert.ok(active.pending?.text, "Second turn has actual generated speech");
  report.second_response = active;
  await page.locator("#interrupt").click();
  const stoppedResponse = await page.request.get(`${base}/api/v1/characters/${sessionId}`);
  const stopped = await stoppedResponse.json();
  report.interrupted = { epoch: stopped.epoch, body: stopped.body };
  assert.ok(stopped.epoch > active.epoch);
  assert.equal(stopped.pending, null);
  assert.ok(Object.keys(stopped.body.pose).length > 15);
  const prior = completed.events.find(event => event.kind === "playback_feedback").feedback;
  const stale = await page.request.post(`${base}/api/v1/characters/${sessionId}/feedback`, { data: prior });
  assert.equal(stale.status(), 409);
  await page.screenshot({ path: resolve(output, "held-pose.png") });
  await page.locator("#close").click();
  await page.waitForFunction(() => document.querySelector("#status")?.textContent === "已结束");
  assert.equal((await page.request.get(`${base}/api/v1/characters/${sessionId}`)).status(), 404);
  assert.deepEqual(errors, []);
  report.outcome = "passed";
} catch (error) {
  report.outcome = "failed";
  report.error = String(error);
  await page.screenshot({ path: resolve(output, "failure.png") });
  process.exitCode = 1;
} finally {
  report.finished_at = new Date().toISOString();
  await writeFile(resolve(output, "observation.json"), JSON.stringify(report, null, 2));
  if (sessionId) await page.request.delete(`${base}/api/v1/characters/${sessionId}`).catch(() => {});
  await browser.close();
  console.log(JSON.stringify({ outcome: report.outcome, error: report.error, output, session_id: sessionId }));
}
