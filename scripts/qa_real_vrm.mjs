import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { arch, cpus, platform, release, tmpdir } from "node:os";
import { basename, resolve } from "node:path";

import { chromium } from "playwright";

const baseUrl = process.env.VIREA_QA_BASE_URL || "http://127.0.0.1:8000";
const dataSource = process.env.VIREA_QA_DATA_SOURCE || "full";
const dataset = process.env.VIREA_QA_DATASET || "susuinteracts";
const sampleId = process.env.VIREA_QA_SAMPLE_ID || "fbx_to_json_data_susu_retarget_maya/20250905/Human_0904_152-8_01";
const vrmPath = resolve(process.env.VIREA_VRM_PATH || "");
const durationMs = Math.max(2_000, Number(process.env.VIREA_QA_DURATION_MS || 10_000));
const warmupMs = Math.max(0, Number(process.env.VIREA_QA_WARMUP_MS || 30_000));
const timingRepeats = Math.max(1, Number(process.env.VIREA_QA_REPEATS || 3));
const stressAnnotationCount = Math.max(0, Number(process.env.VIREA_QA_STRESS_ANNOTATIONS || 100));
const browserPath = process.env.VIREA_QA_BROWSER_PATH
  ? resolve(process.env.VIREA_QA_BROWSER_PATH)
  : null;
const outputPrefix = resolve(
  process.env.VIREA_QA_OUTPUT_PREFIX || `${tmpdir()}/virea-real-vrm-${Date.now()}`,
);

if (!process.env.VIREA_VRM_PATH || !existsSync(vrmPath)) {
  throw new Error("Set VIREA_VRM_PATH to a readable local .vrm file; the model is never copied into the repository.");
}
if (browserPath && !existsSync(browserPath)) {
  throw new Error(`VIREA_QA_BROWSER_PATH does not exist: ${browserPath}`);
}

const browser = await chromium.launch({
  headless: true,
  ...(browserPath ? { executablePath: browserPath } : {}),
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1 });
const cdp = await page.context().newCDPSession(page);
await cdp.send("Performance.enable");
const consoleErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => consoleErrors.push(error.message));

try {
  await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
  await page.waitForFunction(
    () => typeof window.__vireaShowcase?.loadSample === "function",
    { timeout: 30_000 },
  );
  const sampleFacts = await page.evaluate(async ({ dataSource, dataset, sampleId }) => {
    const params = new URLSearchParams({ data_source: dataSource, dataset, q: sampleId, limit: "80" });
    const response = await fetch(`/api/samples?${params}`);
    if (!response.ok) throw new Error(`sample catalog failed: HTTP ${response.status}`);
    const payload = await response.json();
    return payload.items?.find((item) => item.sample_id === sampleId) || null;
  }, { dataSource, dataset, sampleId });
  const previewFps = Number(sampleFacts?.fps || sampleFacts?.preview_fps_fallback);
  if (!Number.isFinite(previewFps) || previewFps <= 0) {
    throw new Error(`sample catalog has no native/profile FPS for ${sampleId}`);
  }
  const previewReady = await page.evaluate(
    (payload) => window.__vireaShowcase.loadSample(payload),
    { dataSource, dataset, sampleId, maxFrames: Math.ceil(15 * previewFps) },
  );
  if (previewReady?.sampleId !== sampleId || Number(previewReady?.frames) < 1) {
    throw new Error(`preview did not reach structured ready state: ${JSON.stringify(previewReady)}`);
  }
  const loadedSampleId = await page.textContent("#sampleTitle");
  if (loadedSampleId !== sampleId) {
    throw new Error(`stale sample response selected ${loadedSampleId}; expected ${sampleId}`);
  }

  await page.setInputFiles("#modelFileInput", vrmPath);
  await page.waitForFunction(
    () => /loaded as VRM/i.test(document.querySelector("#modelStatus")?.textContent || ""),
    null,
    { timeout: 30_000 },
  );
  await page.waitForFunction(
    () => document.querySelector("#modelCanvas")?.dataset.hasVrmHumanoid === "true",
    null,
    { timeout: 15_000 },
  );

  const realDiagnostics = await page.locator("#modelCanvas").evaluate((canvas) => ({
    markerPoolSize: Number(canvas.dataset.markerPoolSize || 0),
    visibleMarkerCount: Number(canvas.dataset.visibleMarkerCount || 0),
    textureCreateCount: Number(canvas.dataset.textureCreateCount || 0),
    anchorModes: canvas.dataset.anchorModes || "",
    hasVrmHumanoid: canvas.dataset.hasVrmHumanoid === "true",
    normalizedPoseAxisMode: canvas.dataset.normalizedPoseAxisMode || "",
    restFrameCorrectionCount: Number(canvas.dataset.restFrameCorrectionCount || 0),
  }));
  const realDesktopScreenshot = `${outputPrefix}-real-desktop.png`;
  await page.locator(".model-panel").screenshot({ path: realDesktopScreenshot });

  const stressFixture = stressAnnotationCount
    ? await page.evaluate((count) => {
        const parts = ["head", "spine", "left_arm", "right_arm", "left_leg", "right_leg", "object", "contact", "dialogue", "face", "audio"];
        const annotations = Array.from({ length: count }, (_, index) => {
          const bodypart = parts[index % parts.length];
          const context = ["dialogue", "face", "audio", "object", "contact"].includes(bodypart);
          return {
            schema_version: "virea.annotation.v1.0.0",
            id: `qa-stress-${String(index).padStart(3, "0")}`,
            level: context ? "context" : "part",
            type: "qa_performance_fixture",
            text: `Synthetic QA marker ${index + 1}; never interpreted as a dataset-native label`,
            bodypart,
            start_sec: null,
            end_sec: null,
            start_frame: null,
            end_frame: null,
            confidence: null,
            source: "scripts/qa_real_vrm.mjs",
            provenance: "fallback",
            reasoning: "Synthetic local-only stress fixture for allocation and layout measurement.",
            original: { synthetic_qa_fixture: true, ordinal: index },
            clipped: false,
            extras: {},
          };
        });
        return window.__vireaShowcase.setAnnotationFixture(annotations);
      }, stressAnnotationCount)
    : { annotationCount: 0, activeCount: 0, diagnostics: realDiagnostics };

  const diagnosticsBefore = await page.locator("#modelCanvas").evaluate((canvas) => ({
    markerPoolSize: Number(canvas.dataset.markerPoolSize || 0),
    visibleMarkerCount: Number(canvas.dataset.visibleMarkerCount || 0),
    textureCreateCount: Number(canvas.dataset.textureCreateCount || 0),
    anchorModes: canvas.dataset.anchorModes || "",
  }));

  await page.click("#modelPlayButton");
  if (warmupMs > 0) await page.waitForTimeout(warmupMs);
  await page.evaluate(() => {
    window.__vireaLongTasks = [];
    window.__vireaLongTaskObserver?.disconnect?.();
    if (typeof PerformanceObserver === "function") {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          window.__vireaLongTasks.push({ startTime: entry.startTime, duration: entry.duration });
        }
      });
      try {
        observer.observe({ type: "longtask", buffered: false });
        window.__vireaLongTaskObserver = observer;
      } catch {
        // Some browsers do not expose the Long Tasks API in headless mode.
      }
    }
  });
  const metricsBefore = await cdp.send("Performance.getMetrics");
  const timingRuns = [];
  for (let repeat = 0; repeat < timingRepeats; repeat += 1) {
    timingRuns.push(await page.evaluate(
      (testDurationMs) => new Promise((resolveTiming) => {
        const deltas = [];
        const started = performance.now();
        let previous = started;
        const step = (now) => {
          if (now > previous) deltas.push(now - previous);
          previous = now;
          if (now - started >= testDurationMs) {
            const sorted = deltas.slice().sort((a, b) => a - b);
            const percentile = (p) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))] || 0;
            resolveTiming({
              sampleCount: sorted.length,
              p50Ms: percentile(0.50),
              p95Ms: percentile(0.95),
              p99Ms: percentile(0.99),
              maxMs: sorted.at(-1) || 0,
              over20Ms: sorted.filter((value) => value > 20).length,
            });
            return;
          }
          requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      }),
      durationMs,
    ));
  }
  const metricsAfter = await cdp.send("Performance.getMetrics");
  const metricMap = (payload) => Object.fromEntries(payload.metrics.map((metric) => [metric.name, metric.value]));
  const beforeMap = metricMap(metricsBefore);
  const afterMap = metricMap(metricsAfter);
  const performanceMetricNames = ["TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "JSHeapUsedSize", "Nodes"];
  const performanceMetrics = Object.fromEntries(performanceMetricNames.map((name) => [name, {
    before: beforeMap[name] ?? null,
    after: afterMap[name] ?? null,
    delta: beforeMap[name] === undefined || afterMap[name] === undefined ? null : afterMap[name] - beforeMap[name],
  }]));
  const longTasks = await page.evaluate(() => window.__vireaLongTasks || []);
  const worstRun = timingRuns.reduce((worst, run) => run.p95Ms > worst.p95Ms ? run : worst, timingRuns[0]);
  const frameTiming = {
    ...worstRun,
    repeatCount: timingRepeats,
    worstP95Ms: worstRun.p95Ms,
    runs: timingRuns,
    longTaskCount: longTasks.length,
    maxLongTaskMs: Math.max(0, ...longTasks.map((item) => item.duration)),
    cdpMetrics: performanceMetrics,
  };
  if ((await page.textContent("#modelPlayButton")) === "Pause") await page.click("#modelPlayButton");

  const diagnosticsAfter = await page.locator("#modelCanvas").evaluate((canvas) => ({
    markerPoolSize: Number(canvas.dataset.markerPoolSize || 0),
    visibleMarkerCount: Number(canvas.dataset.visibleMarkerCount || 0),
    textureCreateCount: Number(canvas.dataset.textureCreateCount || 0),
    anchorModes: canvas.dataset.anchorModes || "",
  }));
  const stressDesktopScreenshot = `${outputPrefix}-stress-desktop.png`;
  await page.locator(".model-panel").screenshot({ path: stressDesktopScreenshot });

  await page.setViewportSize({ width: 760, height: 900 });
  await page.waitForTimeout(250);
  const narrowLayout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    overlayPosition: getComputedStyle(document.querySelector("#modelAnnotationOverlay")).position,
  }));
  const narrowScreenshot = `${outputPrefix}-stress-narrow.png`;
  await page.locator(".model-panel").screenshot({ path: narrowScreenshot });

  let gitCommit = "unavailable";
  let workingTreeDirty = null;
  try {
    gitCommit = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
    workingTreeDirty = Boolean(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim());
  } catch {
    // The QA result remains useful outside a Git checkout.
  }
  const browserRuntime = await page.evaluate(() => {
    const canvas = document.querySelector("#modelCanvas");
    const gl = canvas?.getContext?.("webgl2") || canvas?.getContext?.("webgl") || null;
    const debug = gl?.getExtension?.("WEBGL_debug_renderer_info") || null;
    return {
      userAgent: navigator.userAgent,
      hardwareConcurrency: navigator.hardwareConcurrency || null,
      devicePixelRatio: window.devicePixelRatio,
      webglVendor: debug ? gl.getParameter(debug.UNMASKED_VENDOR_WEBGL) : null,
      webglRenderer: debug ? gl.getParameter(debug.UNMASKED_RENDERER_WEBGL) : null,
    };
  });

  const result = {
    schema_version: "virea.real_vrm_qa.v1",
    base_url: baseUrl,
    dataset,
    sample_id: sampleId,
    loaded_sample_id: loadedSampleId,
    vrm_file: basename(vrmPath),
    git_commit: gitCommit,
    working_tree_dirty: workingTreeDirty,
    environment: {
      os: `${platform()} ${release()} ${arch()}`,
      cpu: cpus()[0]?.model || "unknown",
      logical_cpu_count: cpus().length,
      browser: browser.version(),
      ...browserRuntime,
      viewport: { width: 1280, height: 720, deviceScaleFactor: 1 },
    },
    model_status: await page.textContent("#modelStatus"),
    real_diagnostics: realDiagnostics,
    stress_fixture: {
      requested_annotation_count: stressAnnotationCount,
      warmup_ms: warmupMs,
      measured_ms: durationMs,
      timing_repeats: timingRepeats,
      ...stressFixture,
    },
    diagnostics_before: diagnosticsBefore,
    diagnostics_after: diagnosticsAfter,
    frame_timing: frameTiming,
    narrow_layout: narrowLayout,
    screenshots: [realDesktopScreenshot, stressDesktopScreenshot, narrowScreenshot],
    console_errors: consoleErrors,
  };
  console.log(JSON.stringify(result, null, 2));

  const failed = [
    !realDiagnostics.hasVrmHumanoid,
    realDiagnostics.normalizedPoseAxisMode !== "three-vrm-portable",
    realDiagnostics.restFrameCorrectionCount !== 0,
    stressAnnotationCount > 0 && !diagnosticsAfter.anchorModes.includes("humanoid"),
    stressAnnotationCount > 0 && stressFixture.activeCount < stressAnnotationCount,
    stressAnnotationCount > 0 && diagnosticsBefore.markerPoolSize > 10,
    diagnosticsAfter.markerPoolSize !== diagnosticsBefore.markerPoolSize,
    diagnosticsAfter.textureCreateCount !== diagnosticsBefore.textureCreateCount,
    frameTiming.p95Ms >= 20,
    narrowLayout.scrollWidth > narrowLayout.clientWidth,
    narrowLayout.overlayPosition !== "static",
    consoleErrors.length > 0,
  ].some(Boolean);
  if (failed) process.exitCode = 1;
} finally {
  await browser.close();
}
