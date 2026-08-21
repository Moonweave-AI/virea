import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const expectedDatasets = ["amass", "babel", "beat", "grab", "humanml3d", "motionx", "susuinteracts"];
const expectedRoles = ["hero", "hands", "feet", "facing"];

function argValue(name, fallback = "") {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}

function requiredValue(name, envName) {
  const value = argValue(name, process.env[envName] || "");
  if (!value) throw new Error(`Missing ${name}. Pass ${name} or set ${envName}.`);
  return value;
}

function finitePositive(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${label} must be a positive finite number.`);
  return number;
}

function selectedDatasets() {
  const raw = argValue("--datasets", "").trim();
  if (!raw) return [...expectedDatasets];
  const values = [...new Set(raw.split(",").map((value) => value.trim()).filter(Boolean))];
  const unsupported = values.filter((value) => !expectedDatasets.includes(value));
  if (!values.length || unsupported.length) {
    throw new Error(`--datasets must be a comma-separated subset of: ${expectedDatasets.join(", ")}`);
  }
  return values;
}

function insideRepo(target, label) {
  const relative = path.relative(repoRoot, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} must resolve to a child of the VIREA repository.`);
  }
  return target;
}

function slugPart(value) {
  return String(value)
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 72)
    .toLowerCase();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function sha256File(filePath) {
  return createHash("sha256").update(await fs.readFile(filePath)).digest("hex");
}

function gitFacts() {
  try {
    return {
      commit: execFileSync("git", ["rev-parse", "HEAD"], { cwd: repoRoot, encoding: "utf8" }).trim(),
      working_tree_dirty: Boolean(
        execFileSync("git", ["status", "--porcelain"], { cwd: repoRoot, encoding: "utf8" }).trim(),
      ),
    };
  } catch {
    return { commit: "unavailable", working_tree_dirty: null };
  }
}

function validateSourceManifest(manifest) {
  if (manifest?.schema_version !== "virea.showcase_gallery.v2") {
    throw new Error("Showcase source manifest must use virea.showcase_gallery.v2.");
  }
  const datasets = manifest.datasets;
  if (!datasets || typeof datasets !== "object" || Array.isArray(datasets)) {
    throw new Error("Showcase source manifest has no datasets object.");
  }
  const keys = Object.keys(datasets).sort();
  if (JSON.stringify(keys) !== JSON.stringify([...expectedDatasets].sort())) {
    throw new Error("Showcase source manifest must contain exactly the seven supported datasets.");
  }
  for (const dataset of expectedDatasets) {
    const rows = datasets[dataset];
    if (!Array.isArray(rows) || rows.length !== expectedRoles.length) {
      throw new Error(`${dataset} must have exactly four gallery rows.`);
    }
    const roles = rows.map((row) => row.role).sort();
    if (JSON.stringify(roles) !== JSON.stringify([...expectedRoles].sort())) {
      throw new Error(`${dataset} must define hero, hands, feet, and facing exactly once.`);
    }
    for (const row of rows) {
      if (row.dataset !== dataset || typeof row.sample_id !== "string" || !row.sample_id) {
        throw new Error(`${dataset}/${row.role} has an invalid dataset or sample_id.`);
      }
    }
  }
}

async function waitForSample(page, sampleId) {
  await page.waitForFunction(
    (id) => {
      const title = document.querySelector("#sampleTitle")?.textContent || "";
      const max = Number(document.querySelector("#modelFrameSlider")?.max || -1);
      return title === id && max >= 0;
    },
    sampleId,
    { timeout: 90_000 },
  );
  await page.waitForTimeout(350);
}

async function loadSample(page, dataSource, dataset, sampleId, previewSeconds) {
  await page.waitForFunction(() => Boolean(window.__vireaShowcase?.loadSample), { timeout: 30_000 });
  const sampleFacts = await page.evaluate(async ({ dataSource, dataset, sampleId }) => {
    const params = new URLSearchParams({ data_source: dataSource, dataset, q: sampleId, limit: "80" });
    const response = await fetch(`/api/samples?${params}`);
    if (!response.ok) throw new Error(`sample catalog failed: HTTP ${response.status}`);
    const payload = await response.json();
    return payload.items?.find((item) => item.sample_id === sampleId) || null;
  }, { dataSource, dataset, sampleId });
  if (!sampleFacts) throw new Error(`${dataset}/${sampleId} is not present in the sample catalog.`);
  const result = await page.evaluate(
    (payload) => window.__vireaShowcase.loadSample(payload),
    {
      dataSource,
      dataset,
      sampleId,
      previewSeconds,
      fps: sampleFacts.fps,
      previewFpsFallback: sampleFacts.preview_fps_fallback,
    },
  );
  await waitForSample(page, sampleId);
  return { ...result, sampleFacts };
}

async function assertPortableVrmMotion(page, dataset, sampleId) {
  const diagnostics = await page.evaluate(() => window.__vireaShowcase.vrmDiagnostics());
  const failed = [
    !diagnostics.hasVrmHumanoid,
    diagnostics.motionContractSupported !== true,
    diagnostics.normalizedPoseAxisMode !== "three-vrm-portable-normalized",
    diagnostics.legacyTerminalSelfConjugationCount !== 0,
    diagnostics.targetRestCorrectionCount !== 0,
    diagnostics.restFrameCorrectionCount !== 0,
  ].some(Boolean);
  if (failed) {
    throw new Error(
      `${dataset}/${sampleId} did not reach the verified v3 normalized-pose path: ${JSON.stringify(diagnostics)}`,
    );
  }
  return diagnostics;
}

async function recordCanvas(page, outPath, seconds, bitrate, focusBone, focusDistanceScale) {
  const downloadPromise = page.waitForEvent("download", { timeout: seconds * 1000 + 30_000 });
  await page.evaluate(
    async ({ seconds, bitrate, focusBone, focusDistanceScale }) => {
      const canvas = document.querySelector("#modelCanvas");
      const playButton = document.querySelector("#modelPlayButton");
      if (!canvas || !playButton) throw new Error("model canvas or play button is missing");
      const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp8")
        ? "video/webm;codecs=vp8"
        : "video/webm";
      const stream = canvas.captureStream(24);
      const chunks = [];
      const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: bitrate });
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) chunks.push(event.data);
      });
      const stopped = new Promise((resolve) => recorder.addEventListener("stop", resolve, { once: true }));
      const trackingTimer = focusBone
        ? setInterval(
            () => window.__vireaShowcase.focusVrmBoneForQa(focusBone, focusDistanceScale),
            80,
          )
        : null;
      recorder.start(100);
      if (playButton.textContent !== "Pause") playButton.click();
      await new Promise((resolve) => setTimeout(resolve, seconds * 1000));
      if (playButton.textContent === "Pause") playButton.click();
      recorder.stop();
      await stopped;
      if (trackingTimer) clearInterval(trackingTimer);
      const blob = new Blob(chunks, { type: mimeType });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "clip.webm";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    { seconds, bitrate, focusBone, focusDistanceScale },
  );
  const download = await downloadPromise;
  await download.saveAs(outPath);
}

function galleryHtml(run) {
  const datasets = run.selected_datasets || expectedDatasets;
  const sections = datasets.map((dataset) => {
    const rows = run.datasets[dataset];
    const cards = expectedRoles.map((role) => rows.find((row) => row.role === role));
    const media = cards.map((row) => {
      const cardClass = row.role === "hero" ? "card hero" : "card detail";
      const roleLabel = { hero: "Representative motion", hands: "Hands & fingers", feet: "Ankles & feet", facing: "Facing & root" }[row.role];
      return `<article class="${cardClass}">
        <video controls muted loop playsinline preload="metadata" poster="${escapeHtml(row.poster)}" aria-label="${escapeHtml(`${dataset} ${roleLabel}: ${row.label}`)}">
          <source src="${escapeHtml(row.video)}" type="video/webm">
        </video>
        <div class="card-copy"><strong>${escapeHtml(roleLabel)}</strong><span>${escapeHtml(row.label)}</span></div>
      </article>`;
    }).join("\n");
    return `<section id="${dataset}" class="dataset">
      <div class="section-heading"><span>${escapeHtml(dataset)}</span><small>canonical v3 · verified replay · local-only</small></div>
      <div class="media-grid">${media}</div>
    </section>`;
  }).join("\n");
  const nav = datasets.map((dataset) => `<a href="#${dataset}">${dataset}</a>`).join("");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>VIREA · Local canonical v3 showcase</title>
  <style>
    :root { color-scheme: dark; --ink:#eef3ff; --muted:#a7b1c8; --panel:#11182b; --line:#27324d; --mint:#78e6d0; --violet:#b8a9ff; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; background:radial-gradient(circle at 50% -10%,#25335c 0,#0b1020 42%,#070a12 100%); color:var(--ink); font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
    header { max-width:1220px; margin:0 auto; padding:72px 28px 38px; text-align:center; }
    .eyebrow { color:var(--mint); font-size:.78rem; font-weight:750; letter-spacing:.18em; text-transform:uppercase; }
    h1 { margin:.35rem 0 .7rem; font-size:clamp(2.6rem,8vw,5.8rem); letter-spacing:-.055em; line-height:.95; }
    header p { max-width:760px; margin:0 auto; color:var(--muted); font-size:1.06rem; line-height:1.65; }
    .notice { margin:24px auto 0; max-width:900px; padding:13px 17px; border:1px solid #5d5135; border-radius:14px; background:#251f13; color:#f4deb0; font-size:.88rem; }
    nav { display:flex; flex-wrap:wrap; justify-content:center; gap:9px; margin-top:24px; }
    nav a { color:var(--ink); text-decoration:none; border:1px solid var(--line); background:#10172a; border-radius:999px; padding:7px 12px; font-size:.82rem; }
    main { width:min(1220px,calc(100% - 36px)); margin:0 auto 80px; }
    .dataset { margin:0 0 56px; padding:22px; border:1px solid var(--line); border-radius:24px; background:linear-gradient(145deg,rgba(20,28,49,.96),rgba(10,15,29,.96)); box-shadow:0 28px 80px rgba(0,0,0,.24); }
    .section-heading { display:flex; align-items:baseline; justify-content:space-between; gap:16px; margin:0 3px 17px; }
    .section-heading span { font-size:1.55rem; font-weight:760; text-transform:uppercase; letter-spacing:.03em; }
    .section-heading small { color:var(--muted); }
    .media-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
    .card { overflow:hidden; border:1px solid #303c5b; border-radius:16px; background:#090d17; }
    .card.hero { grid-column:1/-1; }
    video { display:block; width:100%; aspect-ratio:16/9; object-fit:cover; background:#05070d; }
    .card.hero video { aspect-ratio:2.1/1; }
    .card-copy { display:flex; justify-content:space-between; gap:12px; padding:11px 13px 13px; color:var(--muted); font-size:.78rem; }
    .card-copy strong { color:var(--violet); text-transform:uppercase; letter-spacing:.06em; white-space:nowrap; }
    footer { text-align:center; color:#727e99; padding:0 20px 45px; font-size:.78rem; }
    @media (max-width:760px) { header{padding-top:48px}.dataset{padding:14px}.media-grid{grid-template-columns:1fr}.card.hero{grid-column:auto}.card.hero video{aspect-ratio:16/9}.section-heading{align-items:flex-start;flex-direction:column}.card-copy{flex-direction:column;gap:3px} }
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Local verification gallery · ${escapeHtml(run.generated_at)}</div>
    <h1>VIREA</h1>
    <p>Seven motion sources, one replay-verified canonical v3 contract. Every dataset is presented as one large motion view followed by hands, feet, and facing details.</p>
    <div class="notice">Local-only evidence. Dataset and VRM redistribution decisions are not all allowed; do not publish, upload, or cite these files as release evidence.</div>
    <nav>${nav}</nav>
  </header>
  <main>${sections}</main>
  <footer>Generated from ${escapeHtml(run.git.commit)} · source manifest ${escapeHtml(run.source_manifest_sha256)}</footer>
</body>
</html>\n`;
}

async function main() {
  const server = requiredValue("--server", "VIREA_SHOWCASE_SERVER");
  const dataSource = argValue("--data-source", "full");
  const manifestPath = path.resolve(repoRoot, argValue("--manifest", "doc/showcase/showcase-v3-samples.json"));
  const outRoot = insideRepo(
    path.resolve(repoRoot, requiredValue("--out-dir", "VIREA_SHOWCASE_OUTPUT_DIR")),
    "--out-dir",
  );
  const videosDir = path.join(outRoot, "videos");
  const postersDir = path.join(outRoot, "posters");
  // A fresh project-local profile avoids stale cached UI modules while still
  // keeping every browser process artifact inside the repository workspace.
  const profileDir = path.join(outRoot, `browser-profile-${process.pid}-${Date.now()}`);
  const downloadsDir = path.join(outRoot, "browser-downloads");
  const vrmPath = path.resolve(requiredValue("--vrm", "VIREA_SHOWCASE_VRM"));
  const previewSeconds = finitePositive(argValue("--preview-seconds", "15"), "--preview-seconds");
  const seconds = finitePositive(argValue("--seconds", "4.5"), "--seconds");
  const bitrate = finitePositive(argValue("--bitrate", "1800000"), "--bitrate");
  const executablePath = argValue("--executable", process.env.PLAYWRIGHT_CHROMIUM || "");
  const datasets = selectedDatasets();

  await Promise.all([
    fs.mkdir(videosDir, { recursive: true }),
    fs.mkdir(postersDir, { recursive: true }),
    fs.mkdir(profileDir, { recursive: true }),
    fs.mkdir(downloadsDir, { recursive: true }),
  ]);
  const sourceManifestText = await fs.readFile(manifestPath, "utf8");
  const sourceManifest = JSON.parse(sourceManifestText);
  validateSourceManifest(sourceManifest);
  const vrmStat = await fs.stat(vrmPath);
  if (!vrmStat.isFile()) throw new Error("--vrm must point to a readable local file.");

  const { chromium } = await import("playwright");
  const context = await chromium.launchPersistentContext(profileDir, {
    headless: true,
    acceptDownloads: true,
    downloadsPath: downloadsDir,
    viewport: { width: 1280, height: 820 },
    ...(executablePath ? { executablePath } : {}),
  });
  const page = context.pages()[0] || await context.newPage();
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  const git = gitFacts();
  const run = {
    schema_version: "virea.showcase_run.v2",
    generated_at: new Date().toISOString(),
    local_only: true,
    publication_policy: "doc/showcase/publication-policy.json",
    source_manifest: path.relative(repoRoot, manifestPath).replaceAll(path.sep, "/"),
    source_manifest_sha256: createHash("sha256").update(sourceManifestText).digest("hex"),
    data_source: dataSource,
    server,
    git,
    vrm: { file: path.basename(vrmPath), sha256: await sha256File(vrmPath) },
    recording: { preview_seconds: previewSeconds, record_seconds: seconds, bitrate, viewport: [1280, 820] },
    selected_datasets: datasets,
    datasets: {},
  };

  try {
    await page.goto(server, { waitUntil: "networkidle", timeout: 30_000 });
    await page.waitForSelector("#modelFileInput", { timeout: 30_000 });
    await page.setInputFiles("#modelFileInput", vrmPath);
    await page.waitForFunction(
      () => /loaded as VRM/i.test(document.querySelector("#modelStatus")?.textContent || ""),
      null,
      { timeout: 30_000 },
    );

    for (const dataset of datasets) {
      run.datasets[dataset] = [];
      for (const row of sourceManifest.datasets[dataset]) {
        const ordinal = expectedRoles.indexOf(row.role) + 1;
        const stem = `${String(ordinal).padStart(2, "0")}_${dataset}_${row.role}_${slugPart(row.sample_id)}`;
        const videoPath = path.join(videosDir, `${stem}.webm`);
        const posterPath = path.join(postersDir, `${stem}.png`);
        const errorStart = consoleErrors.length;
        console.log(`[showcase] ${dataset}/${row.role}: ${row.sample_id}`);
        const loaded = await loadSample(page, dataSource, dataset, row.sample_id, previewSeconds);
        const frames = Math.max(1, Number(loaded?.frames) || 1);
        const startFrame = Math.min(frames - 1, Math.max(0, Math.floor(frames * Number(row.start_ratio || 0))));
        await page.evaluate((frame) => window.__vireaShowcase.setFrame(frame), startFrame);
        if (row.focus_bone) {
          const focused = await page.evaluate(
            ({ bone, scale }) => window.__vireaShowcase.focusVrmBoneForQa(bone, scale),
            { bone: row.focus_bone, scale: Number(row.focus_distance_scale || 0.42) },
          );
          if (!focused) throw new Error(`${dataset}/${row.role} cannot focus ${row.focus_bone}.`);
        }
        await page.evaluate(() => window.__vireaShowcase.clearVrmAnnotationsForQa());
        await page.waitForTimeout(180);
        const diagnostics = await assertPortableVrmMotion(page, dataset, row.sample_id);
        await page.locator("#modelCanvas").screenshot({ path: posterPath });
        await recordCanvas(
          page,
          videoPath,
          seconds,
          bitrate,
          row.focus_bone,
          Number(row.focus_distance_scale || 0.42),
        );
        const itemErrors = consoleErrors.slice(errorStart);
        if (itemErrors.length) throw new Error(`${dataset}/${row.role} emitted console errors: ${itemErrors.join(" | ")}`);
        const [videoStat, posterStat] = await Promise.all([fs.stat(videoPath), fs.stat(posterPath)]);
        run.datasets[dataset].push({
          ...row,
          sample_facts: loaded.sampleFacts,
          preview_frame_count: frames,
          record_start_frame: startFrame,
          video: `videos/${path.basename(videoPath)}`,
          poster: `posters/${path.basename(posterPath)}`,
          video_bytes: videoStat.size,
          video_sha256: await sha256File(videoPath),
          poster_bytes: posterStat.size,
          poster_sha256: await sha256File(posterPath),
          diagnostics,
          console_errors: [],
        });
        console.log(`[showcase] wrote ${path.relative(repoRoot, videoPath)} (${videoStat.size} bytes)`);
      }
    }

    if (consoleErrors.length) throw new Error(`Showcase run emitted console errors: ${consoleErrors.join(" | ")}`);
    const runPath = path.join(outRoot, "run-manifest.json");
    const galleryPath = path.join(outRoot, "index.html");
    await fs.writeFile(runPath, `${JSON.stringify(run, null, 2)}\n`, "utf8");
    await fs.writeFile(galleryPath, galleryHtml(run), "utf8");
    const galleryPage = await context.newPage();
    await galleryPage.setViewportSize({ width: 1440, height: 1000 });
    await galleryPage.goto(pathToFileURL(galleryPath).href, { waitUntil: "domcontentloaded" });
    await galleryPage.screenshot({ path: path.join(outRoot, "gallery-overview.png"), fullPage: true });
    await galleryPage.close();
    console.log(`[showcase] rendered ${datasets.length * expectedRoles.length} v3 clips; open ${galleryPath}`);
  } finally {
    await context.close();
    await Promise.all([
      fs.rm(profileDir, { recursive: true, force: true }),
      fs.rm(downloadsDir, { recursive: true, force: true }),
    ]);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
