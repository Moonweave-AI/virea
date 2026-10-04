/** Real application + LLM + cloned TTS + native worker, with unaccelerated Studio exports. */
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [backend, avatar, output, base = "http://127.0.0.1:18000", selected = "all", controls = ""] = process.argv.slice(2);
if (!output || !["motioncraft", "syntalker"].includes(backend)) throw new Error("usage: node unified_demo_e2e.mjs BACKEND AVATAR OUTPUT [API] [TASK_ID|all]");
const tasks = JSON.parse(await readFile(new URL("../../configs/character/demo-tasks.json", import.meta.url), "utf8"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, acceptDownloads: true });
const errors = [];
page.on("pageerror", e => errors.push(String(e)));
const saveDownload = async (selector, destination) => {
  const event = page.waitForEvent("download", { timeout: 180000 });
  void event.catch(() => {});
  await page.locator(selector).click();
  await (await event).saveAs(destination);
};
try {
  for (const task of tasks.filter(t => selected === "all" || selected.split(",").includes(t.id))) {
    const id = `${backend}-${task.id}`, report = { ...task, backend, started_at: new Date().toISOString(), samples: [], errors: [] };
    let sessionId;
    try {
      await page.goto(`${base}/app/character.html`);
      await page.waitForFunction(() => document.querySelector("#motion-backend")?.options.length === 3);
      await page.locator("#motion-backend").selectOption(backend);
      await page.locator("#avatar").setInputFiles(resolve(avatar));
      await page.waitForFunction(() => !document.querySelector("#start").disabled, {}, { timeout: 30000 });
      const created = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/characters"));
      await page.locator("#start").click();
      const creationResponse = await created;
      const creation = await creationResponse.json();
      assert.ok(creationResponse.ok(), `session creation failed: ${JSON.stringify(creation)}`);
      assert.equal(creation.motion_backend, backend); sessionId = creation.id;
      await page.locator("#message").fill(task.task);
      await page.locator("#send").click();
      const deadline = Date.now() + 45 * 60000;
      let complete = false;
      while (Date.now() < deadline) {
        const state = await (await page.request.get(`${base}/api/v1/characters/${sessionId}`)).json();
        if (state.status === "error") throw new Error(JSON.stringify(state.events.slice(-3)));
        const uiError = await page.locator("#error").textContent();
        if (uiError) throw new Error(uiError);
        if (state.performance && !report.performance) report.performance = state.performance;
        if (state.pending?.performance && !report.packet) {
          report.packet = state.pending;
          const assets = await page.request.get(`${base}${state.pending.performance.asset_url}`);
          await writeFile(resolve(output, `${id}-motion.json`), await assets.body());
          if (state.pending.audio_url) {
            const audio = await page.request.get(`${base}${state.pending.audio_url}`);
            await writeFile(resolve(output, `${id}.wav`), await audio.body());
          }
        }
        if (state.status === "awaiting_playback") {
          report.samples.push(await page.locator("canvas").evaluate(canvas => ({ ...canvas.dataset })));
          if (report.samples.length === 4) await page.screenshot({ path: resolve(output, `${id}-playing.png`) });
          if (controls === "--controls" && !report.pause_verified && Number(report.samples.at(-1).bodyElapsed) > 6) {
            await page.locator("#pause").click();
            await page.waitForFunction(() => document.querySelector("#pause").textContent.includes("继续"));
            await page.waitForTimeout(100);
            const before = Number(await page.locator("canvas").getAttribute("data-body-elapsed"));
            await page.waitForTimeout(800);
            const after = Number(await page.locator("canvas").getAttribute("data-body-elapsed"));
            assert.ok(Math.abs(after - before) < .03, "body clock must freeze with audio pause");
            await page.locator("#pause").click();
            report.pause_verified = { before, after, wall_wait_ms: 800 };
          }
        }
        if (state.status === "waiting" && state.history.at(-1)?.role === "assistant") {
          report.completed = state; complete = true; break;
        }
        await page.waitForTimeout(500);
      }
      assert.ok(complete, "native performance did not complete before timeout");
      const feedback = report.completed.events.filter(e => e.kind === "playback_feedback");
      assert.ok(feedback.length && feedback.every(e => e.feedback.status === "completed"));
      assert.ok(report.completed.performance.native_history);
      assert.ok(report.completed.events.some(e => e.kind === "motion_window_generated"));
      assert.ok(report.samples.every(s => !s.bodyOwner || [backend, "hold"].includes(s.bodyOwner)), "selected family owns the body throughout");
      await page.waitForFunction(() => !document.querySelector("#export-video").disabled, {}, { timeout: 15000 });
      await page.locator(".playback-tools > summary").click();
      await page.locator("#export-video").click();
      await page.getByRole("dialog", { name: "导出视频" }).waitFor({ timeout: 180000 });
      await saveDownload('dialog[aria-label="导出视频"] a[download]', resolve(output, `${id}.webm`));
      await page.getByRole("dialog", { name: "导出视频" }).getByRole("button", { name: "关闭" }).click();
      await page.locator("#trace-toggle").click();
      await page.locator("#trace-export").click();
      await page.getByRole("dialog", { name: "导出 JSON" }).waitFor();
      await saveDownload('dialog[aria-label="导出 JSON"] a[download]', resolve(output, `${id}-trace.json`));
      await page.getByRole("dialog", { name: "导出 JSON" }).getByRole("button", { name: "关闭", exact: true }).click();
      if (controls === "--controls") {
        await page.locator("#trace-close").click();
        const submitted = await page.request.post(`${base}/api/v1/characters/${sessionId}/performances`, {
          data: { motions: [{ id: "interrupt-check", start_seconds: 0, duration_seconds: 6, prompt: "A person slowly raises both arms." }], speech: [] },
        });
        assert.ok(submitted.ok());
        const epoch = (await submitted.json()).epoch;
        await page.waitForFunction(() => document.querySelector("canvas")?.dataset.bodyStatus === "playing"
          && Number(document.querySelector("canvas").dataset.bodyElapsed) > .5
          && Number(document.querySelector("canvas").dataset.bodyDuration) === 6, {}, { timeout: 180000 });
        await page.locator("#interrupt").click();
        await page.waitForFunction(() => document.querySelector("canvas")?.dataset.bodyOwner === "hold");
        const interrupted = await (await page.request.get(`${base}/api/v1/characters/${sessionId}`)).json();
        assert.ok(interrupted.epoch > epoch && !interrupted.pending && !interrupted.performance);
        report.interruption_verified = { epoch_before: epoch, epoch_after: interrupted.epoch, status: interrupted.status };
      }
      report.errors = [...errors]; assert.deepEqual(report.errors, []);
      const plan = report.completed.performance;
      const speechEnd = Math.max(...plan.speech.map(s => s.start_seconds + s.duration_seconds));
      report.plan_checks = { duration: plan.duration_seconds, expected: task.expected_seconds,
        silent_tail: plan.duration_seconds - speechEnd, minimum_silent_tail: task.minimum_silent_tail_seconds };
      assert.ok(Math.abs(plan.duration_seconds - task.expected_seconds) <= 1, "planned total duration differs from the requested task");
      assert.ok(report.plan_checks.silent_tail >= task.minimum_silent_tail_seconds, "requested silent closing motion is missing");
      report.outcome = "passed";
      console.log(JSON.stringify({ id, outcome: report.outcome, duration: report.completed.performance.duration_seconds }));
    } catch (error) {
      report.outcome = "failed"; report.error = String(error); process.exitCode = 1;
      await page.screenshot({ path: resolve(output, `${id}-failure.png`) });
      console.error(JSON.stringify({ id, error: String(error) }));
    } finally {
      await writeFile(resolve(output, `${id}.json`), JSON.stringify(report, null, 2));
      if (sessionId) await page.request.delete(`${base}/api/v1/characters/${sessionId}`).catch(() => {});
    }
    if (report.outcome !== "passed") break;
  }
} finally { await browser.close(); }
