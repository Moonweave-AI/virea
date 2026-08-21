import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { arch, platform, release } from "node:os";
import { dirname, basename, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  VIEWER_TELEMETRY_SCHEMA,
  acceptanceDefaults,
  applicationJavascriptHttpGetObservation,
  assertPortablePayload,
  assertExternalPath,
  buildManagedApiLifecycle,
  buildBrowserObservation,
  fetchJsonWithTimeout,
  isApplicationJavascriptUrl,
  isVrmaArtifactUrl,
  parseCli,
  portableDiagnosticPayload,
  projectedBounds,
  screenshotRecord,
  stopManagedApi,
  waitForApiHealth,
  waitForLoopbackPortClosed,
  vrmaHttpGetObservation,
} from "./lib/production-e2e-evidence.mjs";

const checkoutRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const options = parseCli(process.argv.slice(2));
const baseUrl = new URL(options["base-url"] || process.env.VIREA_E2E_BASE_URL || "http://127.0.0.1:8000");
if (!["127.0.0.1", "localhost", "[::1]"].includes(baseUrl.hostname)) {
  throw new Error("production browser E2E connects only to the loopback control plane");
}
const modelId = options["model-id"] || process.env.VIREA_E2E_MODEL_ID;
if (!modelId) throw new Error("--model-id is required");
function positiveTimeoutOption(name, fallback) {
  const raw = options[name] ?? fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) throw new Error(`--${name} must be a positive duration`);
  return value;
}
const apiReadinessTimeoutMs = positiveTimeoutOption("api-readiness-timeout-ms", 60_000);
const apiReadinessAttemptTimeoutMs = positiveTimeoutOption(
  "api-readiness-attempt-timeout-ms",
  2_000,
);
const existingJobId = options["existing-job-id"] || process.env.VIREA_E2E_EXISTING_JOB_ID || null;
const managedVireaHome = options["virea-home"] || process.env.VIREA_HOME || null;
const outputDir = assertExternalPath(
  options["output-dir"] || process.env.VIREA_E2E_OUTPUT_DIR || "",
  checkoutRoot,
  "evidence output directory",
);
const avatarPath = assertExternalPath(
  options.vrm || process.env.VIREA_E2E_VRM || "",
  checkoutRoot,
  "VRM input",
);
if (!existsSync(avatarPath) || !/\.(vrm|glb)$/i.test(avatarPath)) {
  throw new Error("--vrm must identify a readable external .vrm/.glb asset");
}
const avatarUsageBasis = options["vrm-usage-basis"] || process.env.VIREA_E2E_VRM_USAGE_BASIS;
if (!avatarUsageBasis?.trim()) {
  throw new Error("--vrm-usage-basis is required; the runner never redistributes the Avatar");
}
if (existsSync(outputDir) && readdirSync(outputDir).length > 0) {
  throw new Error(`evidence output directory must be empty: ${outputDir}`);
}
mkdirSync(outputDir, { recursive: true });

const runId = `browser-${modelId}-${new Date().toISOString().replaceAll(/[-:.TZ]/g, "")}-${process.pid}`;
const startedAt = new Date().toISOString();
const failurePath = resolve(outputDir, "browser-e2e-failure.json");
const observationPath = resolve(outputDir, "browser-observation.json");
const managedApiLifecyclePath = resolve(outputDir, "managed-api-lifecycle.json");
const screenshotPaths = {
  job_result: resolve(outputDir, "job-result.png"),
  viewer: resolve(outputDir, "viewer.png"),
  canvas: resolve(outputDir, "viewer-canvas.png"),
};
const consoleErrors = [];
const consoleWarnings = [];
const pageErrors = [];
const requestFailures = [];
const applicationJavascriptRequests = [];
const applicationJavascriptResponseCaptures = [];
const vrmaArtifactRequests = [];
const vrmaArtifactResponseCaptures = [];
let serverProcess = null;
let serverStartedAt = null;
let serverProcessSpawned = false;
let serverSpawnError = null;
let browser = null;
let browserRunSucceeded = false;
let currentStage = "runner_initialization";

function diagnosticKnownPaths() {
  const browserPath = options["browser-path"] || process.env.VIREA_E2E_BROWSER_PATH;
  const python = options.python || process.env.VIREA_E2E_PYTHON;
  return [
    { path: avatarPath, token: `\${VRM_ASSET}/${basename(avatarPath)}` },
    { path: outputDir, token: "${EVIDENCE_BUNDLE}" },
    { path: options["web-dist"], token: "${WEB_DIST}" },
    { path: browserPath, token: "${BROWSER_EXECUTABLE}" },
    { path: python, token: "${PYTHON_EXECUTABLE}" },
    { path: checkoutRoot, token: "${CHECKOUT}" },
  ].filter((replacement) => (
    typeof replacement.path === "string"
    && replacement.path.trim()
    && isAbsolute(replacement.path)
  ));
}

function scrubFailureDiagnostic(diagnostic) {
  const scrubbed = portableDiagnosticPayload(diagnostic, {
    home: managedVireaHome,
    knownPaths: diagnosticKnownPaths(),
  });
  try {
    assertPortablePayload(scrubbed, "browser failure");
    return scrubbed;
  } catch {
    return {
      schema_version: "virea.production_browser_e2e_failure.v1.0.0",
      run_id: runId,
      recorded_at: new Date().toISOString(),
      model_id: modelId,
      failure: {
        type: String(diagnostic?.failure?.type || "Error"),
        stage: String(diagnostic?.failure?.stage || "unknown"),
        message: "local path detail redacted",
      },
      eligible_for_promotion: false,
    };
  }
}

function startApi() {
  if (!options["start-api"]) return;
  const vireaHome = managedVireaHome;
  if (!vireaHome) throw new Error("--start-api requires --virea-home");
  const python = options.python || process.env.VIREA_E2E_PYTHON || "python";
  const port = Number(baseUrl.port || 80);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error("base URL port is invalid");
  const stdoutFd = openSync(resolve(outputDir, "api.stdout.log"), "a");
  const stderrFd = openSync(resolve(outputDir, "api.stderr.log"), "a");
  const environment = { ...process.env, VIREA_HOME: resolve(vireaHome) };
  if (options["web-dist"]) environment.VIREA_WEB_DIST = resolve(options["web-dist"]);
  try {
    serverStartedAt = new Date().toISOString();
    serverProcess = spawn(
      python,
      [
        "-m", "virea_cli.main", "serve",
        "--host", "127.0.0.1",
        "--port", String(port),
        "--virea-home", resolve(vireaHome),
        "--shutdown-on-stdin-eof",
      ],
      { cwd: checkoutRoot, env: environment, shell: false, stdio: ["pipe", stdoutFd, stderrFd] },
    );
    serverProcess.once("spawn", () => {
      serverProcessSpawned = true;
    });
    serverProcess.once("error", (error) => {
      serverSpawnError = error;
    });
  } finally {
    closeSync(stdoutFd);
    closeSync(stderrFd);
  }
}

async function stopApi() {
  if (!serverProcess) {
    return {
      stdin_eof_requested: false,
      graceful: false,
      forced: false,
      exit_code: null,
      exit_signal: null,
    };
  }
  if (serverSpawnError || !serverProcessSpawned) {
    return {
      stdin_eof_requested: false,
      graceful: false,
      forced: false,
      // Node exposes the platform spawn errno as `exitCode` (for example
      // -4058 for Windows ENOENT) even though no child process existed.  The
      // lifecycle contract keeps process creation and process exit separate:
      // a failed spawn therefore has no process exit fact.
      exit_code: null,
      exit_signal: null,
    };
  }
  return stopManagedApi(serverProcess);
}

function firstVrma(result) {
  const records = (result?.exports || []).filter((record) => (
    String(record.format).toLowerCase() === "vrma" || String(record.locator).toLowerCase().endsWith(".vrma")
  ));
  if (records.length !== 1) throw new Error(`expected exactly one VRMA export, observed ${records.length}`);
  return records[0];
}

async function apiJson(path, timeoutMs = 30_000) {
  return fetchJsonWithTimeout(new URL(path, baseUrl), {
    timeoutMs,
    label: path,
  });
}

function responseContentLength(response, label) {
  const raw = response.headers()["content-length"];
  if (raw == null) return null;
  if (!/^[1-9]\d*$/.test(raw)) throw new Error(`${label} response Content-Length is invalid: ${raw}`);
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) throw new Error(`${label} response Content-Length is unsafe: ${raw}`);
  return value;
}

async function existingGeneration(jobId) {
  const job = await apiJson(`/api/v1/jobs/${encodeURIComponent(jobId)}`);
  if (job.state !== "SUCCEEDED") throw new Error(`${jobId} is not SUCCEEDED`);
  if (job.model_id !== modelId) throw new Error(`${jobId} belongs to ${job.model_id}, not ${modelId}`);
  const request = typeof job.request_json === "string" ? JSON.parse(job.request_json) : job.request;
  if (!request) throw new Error(`${jobId} does not expose its immutable request`);
  const result = await apiJson(`/api/v1/jobs/${encodeURIComponent(jobId)}/result`);
  const modelResultLocator = result?.tracks?.model_result;
  if (typeof modelResultLocator !== "string" || !modelResultLocator) {
    throw new Error(`${jobId} result has no ModelResult track`);
  }
  const name = basename(modelResultLocator.replaceAll("\\", "/"));
  const modelResult = await apiJson(
    `/api/v1/results/${encodeURIComponent(result.result_id)}/artifacts/${encodeURIComponent(name)}`,
  );
  return { job, request, result, model_result: modelResult };
}

try {
  currentStage = "managed_api_startup";
  startApi();
  await new Promise((resolveWait) => setImmediate(resolveWait));
  if (serverSpawnError) throw serverSpawnError;
  if (serverProcess && serverProcess.exitCode != null) {
    throw new Error(`managed API exited during startup with code ${serverProcess.exitCode}`);
  }
  const health = await waitForApiHealth(baseUrl, {
    timeoutMs: apiReadinessTimeoutMs,
    attemptTimeoutMs: apiReadinessAttemptTimeoutMs,
  });
  currentStage = "model_catalog";
  const manifests = await apiJson("/api/v1/models");
  const manifest = manifests.find((candidate) => candidate?.model?.id === modelId);
  if (!manifest) throw new Error(`model catalog does not contain ${modelId}`);
  const defaults = acceptanceDefaults(manifest);
  const timeoutMs = Math.ceil(Number(manifest.production_acceptance.timeout_seconds) * 1000) + 120_000;
  const persistedGeneration = existingJobId ? await existingGeneration(existingJobId) : null;
  if (persistedGeneration) {
    assert.deepStrictEqual(
      persistedGeneration.request,
      defaults.request,
      "existing job request must equal the manifest acceptance request",
    );
  }

  currentStage = "browser_launch";
  const { chromium } = await import("playwright");
  const executablePath = options["browser-path"] || process.env.VIREA_E2E_BROWSER_PATH;
  if (executablePath && !existsSync(resolve(executablePath))) throw new Error("--browser-path does not exist");
  browser = await chromium.launch({
    headless: !options.headed,
    // Headless evidence capture reads the framebuffer for three screenshots.
    // Explicit SwiftShader keeps this production WebGL path deterministic and
    // avoids hardware-driver ReadPixels diagnostics contaminating the page's
    // independently observed zero-warning console contract.
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    ...(executablePath ? { executablePath: resolve(executablePath) } : {}),
  });
  const viewport = { width: 1440, height: 1000 };
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await context.newPage();
  let capturedJobRequest = persistedGeneration?.request || null;
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
    if (message.type() === "warning") consoleWarnings.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("requestfailed", (request) => requestFailures.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText || "failed"}`));
  page.on("request", (request) => {
    if (isApplicationJavascriptUrl(request.url())) {
      applicationJavascriptRequests.push({ url: request.url(), method: request.method() });
    }
    if (isVrmaArtifactUrl(request.url())) {
      vrmaArtifactRequests.push({ url: request.url(), method: request.method() });
    }
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/jobs") {
      capturedJobRequest = request.postDataJSON();
    }
  });
  page.on("response", (response) => {
    if (isApplicationJavascriptUrl(response.url())) {
      applicationJavascriptResponseCaptures.push((async () => {
        const body = await response.body();
        return {
          url: response.url(),
          method: response.request().method(),
          status: response.status(),
          bodyByteLength: body.byteLength,
          contentLength: responseContentLength(response, "application JavaScript"),
        };
      })());
    }
    if (isVrmaArtifactUrl(response.url())) {
      vrmaArtifactResponseCaptures.push((async () => {
        const body = await response.body();
        return {
          url: response.url(),
          method: response.request().method(),
          status: response.status(),
          bodyByteLength: body.byteLength,
          contentLength: responseContentLength(response, "VRMA"),
        };
      })());
    }
  });

  currentStage = "web_application_load";
  const appUrl = new URL("/app/", baseUrl);
  if (existingJobId) appUrl.searchParams.set("job", existingJobId);
  await page.goto(appUrl.href, { waitUntil: "networkidle", timeout: 60_000 });
  const visibleVersionLabel = (await page.locator(".brand small").first().textContent())?.trim() || "";
  const visibleVersionMatch = /^Motion Studio (\d+\.\d+\.\d+)$/.exec(visibleVersionLabel);
  if (!visibleVersionMatch) throw new Error(`visible application version is invalid: ${visibleVersionLabel}`);
  const applicationVersion = visibleVersionMatch[1];
  if (applicationVersion !== health.version) {
    throw new Error(`visible application version ${applicationVersion} differs from control plane ${health.version}`);
  }
  let generation = persistedGeneration;
  if (!generation) {
    currentStage = "web_generation";
    await page.locator('button[data-view="playground"]').click();
    await page.locator("#model-id").waitFor({ state: "visible", timeout: 30_000 });
    await page.locator("#model-id").selectOption(modelId);
    await page.locator("#prompt").waitFor({ state: "visible" });
    const form = await page.evaluate(() => ({
      prompt: document.querySelector("#prompt")?.value,
      seconds: Number(document.querySelector("#seconds")?.value),
      seed: Number(document.querySelector("#seed")?.value),
    }));
    assert.deepStrictEqual(form, { prompt: defaults.prompt, seconds: defaults.seconds, seed: defaults.seed });

    await page.locator("#generate").click();
    try {
      await page.locator("#open-viewer").waitFor({ state: "visible", timeout: timeoutMs });
    } catch (error) {
      const generationOutput = await page.locator("#generation-output").textContent();
      throw new Error(`generation did not publish Viewer action: ${generationOutput || error}`);
    }
    assert.deepStrictEqual(capturedJobRequest, defaults.request, "Web request must equal the manifest acceptance request");
    generation = JSON.parse((await page.locator("#generation-output").textContent()) || "null");
  } else {
    await page.locator("#vrm-canvas").waitFor({ state: "visible", timeout: 30_000 });
  }
  if (generation?.job?.state !== "SUCCEEDED") throw new Error("Web generation did not finish in SUCCEEDED");
  if (generation?.job?.model_id !== modelId) throw new Error("Web generation model binding differs");
  const vrma = firstVrma(generation.result);
  await page.screenshot({ path: screenshotPaths.job_result, fullPage: true });

  currentStage = "viewer_playback";
  if (!persistedGeneration) await page.locator("#open-viewer").click();
  await page.locator("#avatar-file").setInputFiles(avatarPath);
  const canvas = page.locator("#vrm-canvas");
  await page.waitForFunction(
    (telemetrySchema) => {
      const node = document.querySelector("#vrm-canvas");
      return node?.dataset.vireaViewerTelemetry === telemetrySchema
        && node.dataset.viewerState === "playing"
        && node.dataset.webglContextLost === "false"
        && node.dataset.avatarFullyVisible === "true"
        && Number(node.dataset.renderTriangles) > 0;
    },
    VIEWER_TELEMETRY_SCHEMA,
    { timeout: 60_000 },
  );
  const before = await canvas.evaluate((node) => ({
    mixer: Number(node.dataset.mixerTimeSeconds),
    frames: Number(node.dataset.renderFrameCount),
  }));
  const observedIntervalMs = 1_000;
  await page.waitForTimeout(observedIntervalMs);
  const telemetry = await canvas.evaluate((node) => {
    const bounds = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    const visibleInViewport = style.display !== "none"
      && style.visibility !== "hidden"
      && bounds.width > 0
      && bounds.height > 0
      && bounds.left >= 0
      && bounds.top >= 0
      && bounds.right <= window.innerWidth
      && bounds.bottom <= window.innerHeight;
    return {
      telemetryVersion: node.dataset.vireaViewerTelemetry,
      state: node.dataset.viewerState,
      duration: Number(node.dataset.viewerDurationSeconds),
      mixer: Number(node.dataset.mixerTimeSeconds),
      frames: Number(node.dataset.renderFrameCount),
      calls: Number(node.dataset.renderCalls),
      triangles: Number(node.dataset.renderTriangles),
      fullyVisible: node.dataset.avatarFullyVisible === "true" && visibleInViewport,
      projectedBounds: node.dataset.avatarProjectedBounds,
      webgl: {
        context: node.dataset.webglContext,
        vendor: node.dataset.webglVendor,
        renderer: node.dataset.webglRenderer,
        version: node.dataset.webglVersion,
        shadingLanguageVersion: node.dataset.webglShadingLanguageVersion,
        contextLost: node.dataset.webglContextLost === "true",
      },
      canvas: {
        cssWidth: bounds.width,
        cssHeight: bounds.height,
        backingWidth: node.width,
        backingHeight: node.height,
      },
      userAgent: navigator.userAgent,
    };
  });
  if (!(telemetry.mixer > before.mixer)) throw new Error("AnimationMixer time did not advance");
  if (!(telemetry.frames > before.frames)) throw new Error("Viewer render frame count did not advance");
  if (!telemetry.fullyVisible) throw new Error("full Avatar bounds are not visible inside the Canvas viewport");
  if (telemetry.webgl.contextLost) throw new Error("Viewer WebGL context was lost");
  if (consoleErrors.length || consoleWarnings.length || pageErrors.length || requestFailures.length) {
    throw new Error("browser console/network observations are not clean");
  }
  await page.screenshot({ path: screenshotPaths.viewer, fullPage: true });
  await canvas.screenshot({ path: screenshotPaths.canvas });

  const vrmaHttpGet = vrmaHttpGetObservation({
    baseUrl: baseUrl.origin,
    resultId: generation.result.result_id,
    locator: vrma.locator,
    byteLength: vrma.byte_length,
    requests: vrmaArtifactRequests,
    responses: await Promise.all(vrmaArtifactResponseCaptures),
  });
  const applicationJavascriptHttpGet = applicationJavascriptHttpGetObservation({
    requests: applicationJavascriptRequests,
    responses: await Promise.all(applicationJavascriptResponseCaptures),
  });

  const screenshots = Object.entries(screenshotPaths).map(([kind, path]) => (
    screenshotRecord(kind, path, outputDir, statSync(path).size)
  ));
  currentStage = "browser_evidence_serialization";
  const observation = buildBrowserObservation({
    runId,
    startedAt,
    completedAt: new Date().toISOString(),
    generationMode: existingJobId ? "persisted_result_replay" : "fresh_web_job",
    baseUrl: baseUrl.origin,
    application: {
      application_version: applicationVersion,
      visible_version_label: visibleVersionLabel,
      javascript: applicationJavascriptHttpGet,
    },
    manifest,
    request: capturedJobRequest,
    job: generation.job,
    modelResult: generation.model_result,
    result: generation.result,
    vrma,
    vrmaHttpGet,
    browser: {
      name: "Chromium",
      version: browser.version(),
      user_agent: telemetry.userAgent,
      headless: !options.headed,
      viewport: { width: viewport.width, height: viewport.height, device_scale_factor: 1 },
      webgl: {
        context: telemetry.webgl.context,
        vendor: telemetry.webgl.vendor,
        renderer: telemetry.webgl.renderer,
        version: telemetry.webgl.version,
        shading_language_version: telemetry.webgl.shadingLanguageVersion,
        context_lost: false,
      },
    },
    avatarPath,
    avatarUsageBasis: avatarUsageBasis.trim(),
    playback: {
      viewer_telemetry_version: telemetry.telemetryVersion,
      state: telemetry.state,
      duration_seconds: telemetry.duration,
      mixer_time_before_seconds: before.mixer,
      mixer_time_after_seconds: telemetry.mixer,
      observed_interval_ms: observedIntervalMs,
      canvas: {
        css_width: telemetry.canvas.cssWidth,
        css_height: telemetry.canvas.cssHeight,
        backing_width: telemetry.canvas.backingWidth,
        backing_height: telemetry.canvas.backingHeight,
        render_frame_count: telemetry.frames,
        render_calls: telemetry.calls,
        render_triangles: telemetry.triangles,
        fully_visible: true,
        projected_bounds: projectedBounds(telemetry.projectedBounds),
      },
    },
    consoleObservation: {
      errors: consoleErrors,
      warnings: consoleWarnings,
      page_errors: pageErrors,
      request_failures: requestFailures,
    },
    screenshots,
  });
  assertPortablePayload(observation, "browser observation");
  writeFileSync(observationPath, `${JSON.stringify(observation, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  browserRunSucceeded = true;
} catch (error) {
  const diagnostic = scrubFailureDiagnostic({
    schema_version: "virea.production_browser_e2e_failure.v1.0.0",
    run_id: runId,
    recorded_at: new Date().toISOString(),
    model_id: modelId,
    environment: { platform: platform(), release: release(), architecture: arch() },
    failure: {
      type: error?.constructor?.name || "Error",
      stage: currentStage,
      message: String(error?.message || error),
    },
    console: { errors: consoleErrors, warnings: consoleWarnings, page_errors: pageErrors, request_failures: requestFailures },
    eligible_for_promotion: false,
  });
  writeFileSync(failurePath, `${JSON.stringify(diagnostic, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  process.stderr.write(`${JSON.stringify(diagnostic, null, 2)}\n`);
  process.exitCode = 2;
} finally {
  let browserCloseError = null;
  try {
    if (browser) await browser.close();
  } catch (error) {
    browserCloseError = error;
  }

  let shutdown = {
    stdin_eof_requested: false,
    graceful: false,
    forced: false,
    exit_code: null,
    exit_signal: null,
  };
  let shutdownError = null;
  try {
    shutdown = await stopApi();
  } catch (error) {
    shutdownError = error;
  }

  let portCloseMethod = null;
  if (serverProcessSpawned) {
    try {
      portCloseMethod = await waitForLoopbackPortClosed({
        host: baseUrl.hostname,
        port: Number(baseUrl.port || 80),
      });
    } catch {
      portCloseMethod = null;
    }
  }
  const lifecycle = buildManagedApiLifecycle({
    managed: Boolean(options["start-api"]),
    processSpawned: serverProcessSpawned,
    startedAt: serverStartedAt || startedAt,
    stoppedAt: new Date().toISOString(),
    pid: serverProcess?.pid,
    loopbackPort: Number(baseUrl.port || 80),
    shutdown,
    portCloseMethod,
  });
  assertPortablePayload(lifecycle, "managed API lifecycle");
  writeFileSync(
    managedApiLifecyclePath,
    `${JSON.stringify(lifecycle, null, 2)}\n`,
    { encoding: "utf8", flag: "wx" },
  );

  const lifecyclePassed = lifecycle.managed
    && lifecycle.process_spawned
    && Number.isSafeInteger(lifecycle.pid)
    && lifecycle.pid > 0
    && lifecycle.stdin_eof_requested
    && lifecycle.graceful
    && !lifecycle.forced
    && lifecycle.exit_code === 0
    && lifecycle.exit_signal == null
    && lifecycle.port_closed;
  if (browserCloseError || shutdownError || !lifecyclePassed) {
    const lifecycleFailure = scrubFailureDiagnostic({
      schema_version: "virea.production_browser_e2e_failure.v1.0.0",
      run_id: runId,
      recorded_at: new Date().toISOString(),
      model_id: modelId,
      environment: { platform: platform(), release: release(), architecture: arch() },
      failure: {
        type: "ManagedApiLifecycleFailure",
        stage: "managed_api_shutdown",
        message: String(
          browserCloseError?.message
          || shutdownError?.message
          || "managed API did not complete a graceful, unlocked, closed-port shutdown",
        ),
      },
      managed_api_lifecycle_locator: basename(managedApiLifecyclePath),
      eligible_for_promotion: false,
    });
    if (!existsSync(failurePath)) {
      writeFileSync(failurePath, `${JSON.stringify(lifecycleFailure, null, 2)}\n`, {
        encoding: "utf8",
        flag: "wx",
      });
    }
    process.stderr.write(`${JSON.stringify(lifecycleFailure, null, 2)}\n`);
    process.exitCode = 2;
  } else if (browserRunSucceeded && process.exitCode !== 2) {
    process.stdout.write(`${JSON.stringify({
      ok: true,
      run_id: runId,
      observation: basename(observationPath),
      managed_api_lifecycle: basename(managedApiLifecyclePath),
    }, null, 2)}\n`);
  }
}
