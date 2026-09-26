/** Capture real GPU expressions, then replay identical assets against the current stage. */
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [avatar, output, captured, base = "http://127.0.0.1:5173"] = process.argv.slice(2);
if (!avatar || !output) throw new Error("usage: node ending_e2e.mjs AVATAR OUTPUT [CAPTURE_DIR] [VITE_URL]");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, channel: "chrome",
  args: ["--autoplay-policy=no-user-gesture-required"] });
const context = await browser.newContext({ viewport: { width: 960, height: 960 },
  recordVideo: { dir: resolve(output, "video"), size: { width: 960, height: 960 } } });
const page = await context.newPage();
const errors = [], trials = [];
const report = { started_at: new Date().toISOString(), captured: captured || null, trials, errors };
let sessionId, lastPacket;
page.on("pageerror", e => errors.push(String(e)));
const request = async (path, method = "GET", data) => {
  const response = await page.request.fetch(`${base}/api/v1/characters${path}`, { method, data });
  assert.ok(response.ok(), `${method} ${path}: ${response.status()} ${await response.text()}`);
  return response.json();
};
try {
  await page.route("**/app/ending-probe.html", route => route.fulfill({ contentType: "text/html", body: `
    <style>body{margin:0;background:#13221f;color:white;font:20px sans-serif}canvas{width:960px;height:900px}p{margin:10px}</style>
    <input type="file" id="avatar"><canvas></canvas><p id="phase"></p>
    <script type="module">
      import { CharacterStage } from '/app/src/character/stage.ts';
      const stage = new CharacterStage(document.querySelector('canvas'));
      window.probe = { stage, frames: [], done: false, progress: null,
        async load() { await stage.loadAvatar(document.querySelector('input').files[0]); await stage.unlockAudio(); },
        async play(packet) {
          this.frames = []; this.done = false; this.progress = null;
          this.initial = stage.state();
          const durations = await stage.perform(packet, () => {}, progress => {
            this.progress = progress;
            this.frames.push({ ...progress, body: stage.state() });
            document.querySelector('#phase').textContent = packet.text + ' · ' + progress.elapsed.toFixed(2) + ' / ' + progress.motionDuration.toFixed(2);
          });
          this.result = { durations, body: stage.state(), face: Object.fromEntries(
            ['blinkLeft', 'blinkRight', 'aa', 'oh', 'ou', 'happy', 'sad'].map(name => [name, stage.vrm.expressionManager.getValue(name)])) };
          this.done = true;
          return this.result;
        }
      };
    </script>` }));
  await page.goto(`${base}/app/ending-probe.html`);
  await page.waitForFunction(() => window.probe);
  await page.locator("#avatar").setInputFiles(resolve(avatar));
  await page.evaluate(() => window.probe.load());
  const prompts = [
    "自然地打招呼，只说：你好，很高兴见到你。说完请等待。",
    "用手势轻松解释，只说：我们可以先看看周围，再决定往哪里走。说完请等待。",
    "友好地道别，只说：今天聊得很开心，我们下次再见。说完请等待。",
  ];
  for (let index = 0; index < prompts.length; index++) {
    const directory = resolve(output, String(index + 1));
    await mkdir(directory, { recursive: true });
    let packet;
    if (captured) {
      packet = JSON.parse(await readFile(resolve(captured, String(index + 1), "packet.json"), "utf8"));
      for (const [url, name, contentType] of [[packet.audio_url, "audio.wav", "audio/wav"],
        [packet.motion.vrma_url, "motion.vrma", "model/gltf-binary"],
        [`/api/v1/characters/results/${packet.motion.result_id}/face`, "face.json", "application/json"]]) {
        const body = await readFile(resolve(captured, String(index + 1), name));
        await page.route(`**${url}`, route => route.fulfill({ body, contentType }));
      }
    } else {
      sessionId = (await request("", "POST", { playback_mode: "synchronized" })).id;
      await request(`/${sessionId}/messages`, "POST", { text: prompts[index] });
      for (let n = 0; n < 2400; n++) {
        const state = await request(`/${sessionId}`);
        if (state.status === "error") throw new Error(JSON.stringify(state.events.at(-1)));
        if (state.pending) { packet = state.pending; break; }
        await new Promise(r => setTimeout(r, 250));
      }
      assert.ok(packet?.motion && packet?.audio_url, "Real speech and motion must be ready");
      await writeFile(resolve(directory, "packet.json"), JSON.stringify(packet, null, 2));
      for (const [url, name] of [[packet.audio_url, "audio.wav"], [packet.motion.vrma_url, "motion.vrma"],
        [`/api/v1/characters/results/${packet.motion.result_id}/face`, "face.json"]]) {
        const response = await page.request.get(new URL(url, base).href);
        assert.ok(response.ok()); await writeFile(resolve(directory, name), await response.body());
      }
    }
    const playback = page.evaluate(packet => window.probe.play(packet), packet);
    lastPacket = packet;
    let nearEnd = false, voiceEnd = false;
    while (!(await page.evaluate(() => window.probe.done))) {
      const progress = await page.evaluate(() => window.probe.progress);
      if (progress && !nearEnd && progress.elapsed >= progress.audioDuration - 0.3) {
        await page.screenshot({ path: resolve(directory, "before-end.png") }); nearEnd = true;
      }
      if (progress && !voiceEnd && progress.elapsed >= progress.audioDuration) {
        await page.screenshot({ path: resolve(directory, "voice-end.png") }); voiceEnd = true;
      }
      await new Promise(r => setTimeout(r, 30));
    }
    const result = await playback;
    await new Promise(r => setTimeout(r, 350));
    await page.screenshot({ path: resolve(directory, "held.png") });
    const observation = await page.evaluate(() => ({ frames: window.probe.frames, initial: window.probe.initial,
      result: window.probe.result, held: window.probe.stage.state() }));
    await writeFile(resolve(directory, "trajectory.json"), JSON.stringify(observation));
    trials.push({ prompt: prompts[index], packet_id: packet.id, text: packet.text, ...result.durations,
      frames: observation.frames.length, final_body: result.body });
    if (captured) {
      assert.ok(result.durations.motion_seconds > result.durations.audio_seconds + 0.6);
      assert.ok(Object.values(result.face).every(value => Math.abs(value ?? 0) < 1e-6), "facial tracks release at the end");
      assert.deepEqual(observation.held, result.body, "settled pose remains the executed pose");
    }
    console.log(JSON.stringify({ trial: index + 1, ...result.durations, frames: observation.frames.length }));
    if (sessionId) {
      await request(`/${sessionId}/feedback`, "POST", { packet_id: packet.id, epoch: packet.epoch,
        status: "completed", body: result.body, ...result.durations });
      await request(`/${sessionId}`, "DELETE"); sessionId = null;
    }
  }
  if (captured) {
    // A continuing packet must retain its motion, with no per-window recovery delay.
    const continued = await page.evaluate(packet => window.probe.play({ ...packet, continues: true }), lastPacket);
    assert.equal(continued.durations.audio_seconds, continued.durations.motion_seconds);
    report.continuing_packet = continued.durations;

    const playback = page.evaluate(packet => window.probe.play(packet), lastPacket);
    await page.waitForFunction(() => window.probe.progress?.elapsed > window.probe.progress?.audioDuration + 0.2);
    await page.evaluate(() => window.probe.stage.togglePause());
    await page.waitForTimeout(100);
    const pausedBefore = await page.evaluate(() => ({ body: window.probe.stage.state(), progress: window.probe.progress }));
    await page.waitForTimeout(400);
    const pausedAfter = await page.evaluate(() => ({ body: window.probe.stage.state(), progress: window.probe.progress }));
    assert.deepEqual(pausedBefore, pausedAfter, "pause freezes recovery pose and the single clock");
    assert.equal(await page.evaluate(() => window.probe.done), false);
    report.pause_in_recovery = { elapsed: pausedAfter.progress.elapsed, observed_ms: 400, unchanged: true };
    await page.evaluate(() => window.probe.stage.togglePause());
    await playback;

    const interrupted = page.evaluate(packet => window.probe.play(packet).then(() => 'completed', e => e.name), lastPacket);
    await page.waitForFunction(() => window.probe.progress?.elapsed > window.probe.progress?.audioDuration + 0.2);
    const held = await page.evaluate(() => window.probe.stage.stop());
    assert.equal(await interrupted, "AbortError");
    await page.waitForTimeout(400);
    assert.deepEqual(await page.evaluate(() => window.probe.stage.state()), held, "interrupt must retain the recovery pose");
    report.interruption_in_recovery = { unchanged: true, completed: false, body: held };
  }
  assert.deepEqual(errors, []);
  report.outcome = "passed";
} catch (error) {
  report.outcome = "failed"; report.error = String(error); process.exitCode = 1;
} finally {
  if (sessionId) await request(`/${sessionId}`, "DELETE").catch(() => {});
  report.finished_at = new Date().toISOString();
  await writeFile(resolve(output, "observation.json"), JSON.stringify(report, null, 2));
  await context.close(); await browser.close();
  console.log(JSON.stringify({ outcome: report.outcome, error: report.error, output }));
}
