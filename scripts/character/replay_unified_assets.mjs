/** Re-render real generated assets through CharacterStage at normal speed. No inference mocks. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";

const [input, avatar, selected = "all", vite = "http://127.0.0.1:18091", api = "http://127.0.0.1:18000"] = process.argv.slice(2);
if (!input || !avatar) throw new Error("usage: node replay_unified_assets.mjs INPUT AVATAR [comma-separated demo IDs|all] [VITE] [API]");
const hash = value => createHash("sha256").update(value).digest("hex");
const avatarBytes = await readFile(avatar);
const tasks = JSON.parse(await readFile(new URL("../../configs/character/demo-tasks.json", import.meta.url), "utf8"));
const rendererFiles = ["stage.ts", "spatial.ts", "support.ts", "motion_sampling.ts", "video.ts"];
const rendererHashes = Object.fromEntries(await Promise.all(rendererFiles.map(async name => [name, hash(await readFile(new URL(`../../apps/web/src/character/${name}`, import.meta.url)))])));
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
try {
  for (const backend of ["motioncraft", "syntalker"]) for (const task of tasks) {
    const id = `${backend}-${task.id}`;
    if (selected !== "all" && !selected.split(",").includes(id)) continue;
    const report = JSON.parse(await readFile(resolve(input, `${id}.json`), "utf8"));
    assert.equal(report.outcome, "passed", `${id}: generation and browser acceptance must pass`);
    const motionBytes = await readFile(resolve(input, `${id}-motion.json`));
    const audioBytes = await readFile(resolve(input, `${id}.wav`));
    const windows = JSON.parse(motionBytes).windows;
    // Apply the current playback contract to previously generated real trajectories.
    for (const window of windows) window.grounding = "prevent_penetration";
    const page = await browser.newPage({ viewport: { width: 1280, height: 960 }, acceptDownloads: true });
    const errors = [];
    page.on("pageerror", error => errors.push(String(error)));
    try {
      await page.route("**/api/**", async route => {
        const response = await fetch(route.request().url().replace(vite, api));
        await route.fulfill({ status: response.status, contentType: "application/json", body: Buffer.from(await response.arrayBuffer()) });
      });
      await page.route("**/replay.vrm", route => route.fulfill({ body: avatarBytes }));
      await page.route("**/replay.wav", route => route.fulfill({ body: audioBytes, contentType: "audio/wav" }));
      await page.route("**/replay.json", route => route.fulfill({ json: { windows } }));
      await page.route("**/app/asset-replay.html", route => route.fulfill({ contentType: "text/html", body: `<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:100%;height:100%}canvas{width:100%;height:100%;display:block}</style><canvas></canvas><script type="module">import {CharacterStage} from '/app/src/character/stage.ts';import {captureVideo} from '/app/src/character/video.ts';window.stage=new CharacterStage(document.querySelector('canvas'));window.captureVideo=captureVideo;window.ready=true;</script>` }));
      await page.goto(`${vite}/app/asset-replay.html`);
      await page.waitForFunction(() => window.ready);
      const event = page.waitForEvent("download", { timeout: 240000 });
      void event.catch(() => {});
      const rendered = await page.evaluate(async ({ packet, backend, id }) => {
        await stage.loadAvatar(new File([await (await fetch('/replay.vrm')).blob()], 'VRM-Model-1.vrm'), backend);
        await stage.unlockAudio();
        stage.track({ id, epoch: 1, status: "generating" });
        const value = { ...packet, audio_url: '/replay.wav', performance: { ...packet.performance, asset_url: '/replay.json' } };
        // Compile the loaded avatar and decode its real audio before recording the first frame.
        await Promise.all([stage.renderer.compileAsync(stage.scene, stage.camera), stage.loadAudio(value.audio_url)]);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        let caption = "", elapsed = 0;
        const samples = [];
        const blob = await captureVideo(document.querySelector('canvas'), stage.audio, stage.gain,
          () => stage.perform(value, () => {}, progress => {
            caption = progress.caption ?? ""; elapsed = progress.elapsed;
            samples.push({ elapsed, ground: stage.diagnostics().ground_clearance });
          }), () => ({ caption, label: `${backend}  ·  ${elapsed.toFixed(1)}s` }));
        const link = document.createElement('a');link.href = URL.createObjectURL(blob);link.download = id + '-render.webm';link.click();
        return { samples, bytes: blob.size, duration_seconds: elapsed, diagnostics: stage.diagnostics() };
      }, { packet: report.packet, backend, id });
      const destination = resolve(input, `${id}-render.webm`);
      await (await event).saveAs(destination);
      assert.deepEqual(errors, []);
      assert.ok(Math.abs(rendered.duration_seconds - report.packet.performance.duration_seconds) < .1);
      const inMotion = rendered.samples.filter(s => s.elapsed > .1 && s.elapsed < rendered.duration_seconds - .1 && s.ground !== null);
      const clearance = Math.min(...inMotion.map(s => s.ground));
      assert.ok(clearance > -.005, `${id}: feet penetrated the calibrated floor: ${clearance}`);
      await writeFile(resolve(input, `${id}-render.json`), JSON.stringify({
        schema: "virea.generated_asset_replay.v1", id, outcome: "passed", rendered_at: new Date().toISOString(),
        avatar_sha256: hash(avatarBytes), source_motion_sha256: hash(motionBytes), source_audio_sha256: hash(audioBytes),
        video_sha256: hash(await readFile(destination)), renderer_sha256: rendererHashes,
        capture: "Real model trajectory and cloned speech replayed through CharacterStage/captureVideo at normal speed; penetration-only avatar grounding enabled.",
        duration_seconds: rendered.duration_seconds, minimum_ground_clearance: clearance, errors,
      }, null, 2));
      console.log(JSON.stringify({ id, outcome: "rendered", clearance }));
    } finally { await page.close(); }
  }
} finally { await browser.close(); }
