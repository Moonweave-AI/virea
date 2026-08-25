import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { platform } from "node:os";
import { resolve } from "node:path";

import { chromium } from "playwright";
import { createServer as createViteServer } from "vite";

const WEB_ROOT = resolve(import.meta.dirname, "..");


function availableBrowserExecutable() {
  const candidates = [process.env.VIREA_E2E_BROWSER_PATH];
  if (platform() === "win32") {
    candidates.push(
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    );
  } else if (platform() === "darwin") {
    candidates.push("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
  } else {
    candidates.push("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser");
  }
  try {
    candidates.push(chromium.executablePath());
  } catch {
    // An explicitly installed system browser remains a valid test target.
  }
  return candidates.find((candidate) => typeof candidate === "string" && existsSync(candidate)) ?? null;
}


function modelManifest() {
  return {
    model: {
      id: "flood-diffusion-tiny",
      display_name: "Flood Diffusion Tiny",
      status: "integrated_experimental",
      tasks: ["text_to_motion"],
      adapter_family: "humanml3d-motion263-body22",
    },
    output: {
      envelope: "virea.model_result.v1.0.0",
      representation_id: "humanml3d.vector263.v1",
      skeleton_id: "humanml3d.body22.v1",
      fps: 20,
      coordinate_system: "humanml3d.right_handed_y_up_z_forward",
      units: "meters",
      root_translation_semantics: "relative",
      root_rotation_semantics: "relative",
      face_representation_ids: [],
    },
    result_target: {
      representation_id: "virea.canonical211.v3",
      skeleton_id: "vrm1.humanoid52.v1",
    },
    runtime_variants: [{
      id: "flood-diffusion-tiny-cu128",
      availability: "ready",
      entrypoint_argv: ["virea-flood-diffusion-tiny-worker"],
      project_version: "0.1.2",
      runtime_core_epoch: "virea-runtime-core-20260821.2",
    }],
    resources: {},
    licenses: { commercial_allowed: true, requires_acceptance: false },
    installation_state: "READY",
    production_acceptance: {
      schema_version: "virea.production_e2e_acceptance.v1.0.0",
      kind: "production_e2e",
      request: {
        schema_version: "virea.job_request.v1.0.0",
        model_id: "flood-diffusion-tiny",
        task: "text_to_motion",
        input: { prompt: "A person walks forward, turns left, and waves." },
        parameters: { seconds: 4, seed: 42, fps: 20 },
        avatar_id: null,
        idempotency_key: null,
        execution_target: null,
      },
      expected: {
        representation_id: "humanml3d.vector263.v1",
        skeleton_id: "humanml3d.body22.v1",
        min_frames: 40,
        artifacts: ["native_motion", "motion_ir", "retargeted_motion", "vrma"],
      },
      required_stages: [
        "environment_detection",
        "artifact_installation",
        "runtime_build",
        "model_load",
        "inference",
        "native_artifact_validation",
        "motion_ir_conversion",
        "retarget_validation",
        "vrma_export",
        "web_playback",
      ],
      timeout_seconds: 1_800,
    },
  };
}


function respondJson(response, value, status = 200) {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}


async function settlesWithin(promise, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      promise.then(() => true, () => true),
      new Promise((resolveTimeout) => {
        timer = setTimeout(() => resolveTimeout(false), timeoutMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}


test("a hung explicit system diagnostic cannot block bootstrap, Playground, or a persisted deep link", {
  timeout: 30_000,
}, async (context) => {
  const executablePath = availableBrowserExecutable();
  if (!executablePath) {
    context.skip("no installed Chromium-family browser is available");
    return;
  }
  let systemRequestCount = 0;
  let executionDomainRequestCount = 0;
  let executionOptionsRequestCount = 0;
  let executionOptionsMode = "valid";
  let modelCatalogRequestCount = 0;
  let fakeJobRequestCount = 0;
  let generationSubmitCount = 0;
  let submittedGeneration = null;
  let includeResponsiveJob = false;
  const backendSockets = new Set();
  const backend = createHttpServer((request, response) => {
    const path = new URL(request.url, "http://127.0.0.1").pathname;
    if (path === "/api/v1/health") {
      respondJson(response, {
        schema_version: "virea.health.v1.0.0",
        version: "0.4.0",
        status: "ready",
        control_plane_ready: true,
      });
      return;
    }
    if (path === "/api/v1/state") {
      respondJson(response, {
        schema_version: "virea.state_revision.v1.0.0",
        observed_at: "2026-08-23T00:00:00Z",
        // This HTTP-only fixture intentionally advertises no event stream.
        events_url: "",
        virea_home: "X:\\VIREA-DATA\\home",
        revision: {
          jobs: "0:",
          results: "0:",
          installations: "0:",
          models: "1:2026-08-23T00:00:00Z",
          workers: "0::",
        },
      });
      return;
    }
    if (path === "/api/v1/execution-domains") {
      executionDomainRequestCount += 1;
      // Original page bootstrap, recovery-page bootstrap, and the first
      // explicit refresh retain WSL; the second refresh simulates removal.
      const includeWsl = executionDomainRequestCount <= 3;
      respondJson(response, {
        schema_version: "virea.execution_domain_candidates.v1.0.0",
        report_id: "browser-domain-report",
        recorded_at: "2026-08-22T00:00:00Z",
        host_execution_domain: "windows-native",
        execution_domains: [
          {
            schema_version: "virea.execution_domain_report.v1.0.0",
            id: "windows-native",
            kind: "windows-native",
            platform: "win-64",
            architecture: "x86_64",
            is_host: true,
            distribution: null,
          },
          ...(includeWsl ? [{
            schema_version: "virea.execution_domain_report.v1.0.0",
            id: "wsl:Ubuntu-24.04",
            kind: "wsl",
            platform: "linux-64",
            architecture: "x86_64",
            is_host: false,
            distribution: "Ubuntu-24.04",
          }] : []),
        ],
      });
      return;
    }
    if (path === "/api/v1/models/flood-diffusion-tiny/execution-options") {
      executionOptionsRequestCount += 1;
      if (executionOptionsMode === "error") {
        respondJson(response, { detail: "execution discovery unavailable" }, 503);
        return;
      }
      const executionDomains = [
        {
          schema_version: "virea.execution_domain_report.v1.0.0",
          id: "windows-native",
          kind: "windows-native",
          platform: "win-64",
          architecture: "x86_64",
          is_host: true,
          distribution: null,
          warnings: [],
        },
        {
          schema_version: "virea.execution_domain_report.v1.0.0",
          id: "wsl:Ubuntu-24.04",
          kind: "wsl",
          platform: "linux-64",
          architecture: "x86_64",
          is_host: false,
          distribution: "Ubuntu-24.04",
          warnings: [],
        },
      ];
      respondJson(response, {
        schema_version: "virea.model_execution_options.v1.0.0",
        model_id: "flood-diffusion-tiny",
        options: executionOptionsMode === "empty" ? [] : executionDomains.map((domain) => ({
          execution_domain: domain,
          implemented: true,
          selected_runtime_id: "flood-diffusion-tiny-cu128",
          status: "buildable",
          can_build: true,
          reasons: [],
          remediation: [],
          selected_resource_profile: "cuda-component-split",
          selected_memory_strategy: "cuda_component_split",
        })),
      });
      return;
    }
    if (path === "/api/v1/models") {
      modelCatalogRequestCount += 1;
      respondJson(response, [modelManifest()]);
      return;
    }
    if (path === "/api/v1/jobs" && request.method === "POST") {
      generationSubmitCount += 1;
      let body = "";
      request.on("data", (chunk) => { body += String(chunk); });
      request.on("end", () => {
        submittedGeneration = JSON.parse(body);
        setTimeout(() => respondJson(response, {
          id: "job-responsive",
          model_id: "flood-diffusion-tiny",
          task: "text_to_motion",
          state: "QUEUED",
          idempotency_key: submittedGeneration.idempotency_key,
        }, 202), 750);
      });
      return;
    }
    if (path === "/api/v1/jobs") {
      respondJson(response, [{
        id: "fake-job",
        model_id: "fake-motion-v1",
        task: "text_to_motion",
        state: "SUCCEEDED",
      }, ...(includeResponsiveJob ? [{
        id: "job-responsive",
        model_id: "flood-diffusion-tiny",
        task: "text_to_motion",
        state: "QUEUED",
        idempotency_key: submittedGeneration?.idempotency_key ?? "persisted-key",
      }] : [])]);
      return;
    }
    if (path === "/api/v1/jobs/job-responsive") {
      setTimeout(() => respondJson(response, {
        id: "job-responsive",
        model_id: "flood-diffusion-tiny",
        task: "text_to_motion",
        state: "FAILED",
        error_code: "EXPECTED_TEST_STOP",
        error_message: "responsive fixture stops before inference",
        idempotency_key: submittedGeneration?.idempotency_key ?? null,
      }), 500);
      return;
    }
    if (path === "/api/v1/jobs/fake-job") {
      fakeJobRequestCount += 1;
      respondJson(response, { detail: "test-only result must never be requested" }, 500);
      return;
    }
    if (path === "/api/v1/jobs/job-deep") {
      respondJson(response, {
        id: "job-deep",
        model_id: "flood-diffusion-tiny",
        task: "text_to_motion",
        state: "SUCCEEDED",
        error_code: null,
      });
      return;
    }
    if (path === "/api/v1/jobs/job-deep/result") {
      respondJson(response, {
        schema_version: "virea.vrm_motion_result.v1.0.0",
        result_id: "result-deep",
        job_id: "job-deep",
        model_id: "flood-diffusion-tiny",
        actor_ids: ["actor-0"],
        avatar_profile: "vrm1.humanoid52.v1",
        exports: [{ actor_id: "actor-0", format: "vrma", locator: "results/result-deep/motion.vrma" }],
        tracks: { model_result: "results/result-deep/model-result.json" },
      });
      return;
    }
    if (path === "/api/v1/results/result-deep/artifacts/model-result.json") {
      respondJson(response, {
        schema_version: "virea.model_result.v1.0.0",
        result_id: "result-deep",
        job_id: "job-deep",
        model: { id: "flood-diffusion-tiny", version: "0.1.0" },
        native: {
          frame_count: 80,
          fps: 20,
          representation_id: "humanml3d.vector263.v1",
          skeleton_id: "humanml3d.body22.v1",
        },
      });
      return;
    }
    if (path === "/api/v1/results/result-deep/source-skeleton") {
      respondJson(response, {
        schema_version: "virea.source_skeleton_preview.v1.0.0",
        result_id: "result-deep",
        job_id: "job-deep",
        stage: "model_output_pre_retarget",
        representation_id: "humanml3d.vector263.v1",
        skeleton_id: "humanml3d.body22.v1",
        coordinate_system: "world_normalized",
        fps: 20,
        frame_count: 2,
        duration_seconds: 0.1,
        actors: [{
          actor_id: "actor-0",
          joint_names: ["hips", "spine"],
          edges: [[0, 1]],
          positions_xyz: [0, 0, 0, 0, 1, 0, 0.1, 0, 0, 0.1, 1, 0],
        }],
        display_transform: {
          coordinates_normalized_for_preview: true,
          vrm_retarget_applied: false,
        },
        metadata: {},
      });
      return;
    }
    if (path === "/api/v1/results/result-deep/artifacts/motion.vrma") {
      const body = Buffer.from("glTF", "ascii");
      response.writeHead(200, {
        "content-type": "model/gltf-binary",
        "content-length": body.byteLength,
      });
      response.end(body);
      return;
    }
    if (path === "/api/v1/system") {
      systemRequestCount += 1;
      // The real diagnostic can spend more than a minute detecting Windows,
      // WSL, and accelerators. Keep this response slower than the browser's
      // bounded client, then release the proxy socket so the fixture itself
      // cannot leak a permanently open HTTP handle.
      const release = setTimeout(() => {
        if (!response.destroyed && !response.writableEnded) {
          respondJson(response, { detail: "diagnostic fixture released" }, 504);
        }
      }, 1_000);
      release.unref();
      return;
    }
    respondJson(response, { detail: `unhandled test path ${path}` }, 404);
  });
  backend.on("connection", (socket) => {
    backendSockets.add(socket);
    socket.once("close", () => backendSockets.delete(socket));
  });
  await new Promise((resolveListen) => backend.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const backendAddress = backend.address();
  assert.equal(typeof backendAddress, "object");
  const vite = await createViteServer({
    root: WEB_ROOT,
    logLevel: "silent",
    server: {
      host: "127.0.0.1",
      port: 0,
      strictPort: false,
      proxy: {
        "/api": `http://127.0.0.1:${backendAddress.port}`,
      },
    },
  });
  await vite.listen();
  const webAddress = vite.httpServer?.address();
  assert.equal(typeof webAddress, "object");
  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const browserContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const consoleErrors = [];
  const pageErrors = [];
  const preparePage = async () => {
    const page = await browserContext.newPage();
    await page.routeWebSocket(/\/api\/v1\/jobs\/[^/]+\/events$/, (socket) => {
      socket.close();
    });
    await page.addInitScript(() => {
      const nativeSetTimeout = window.setTimeout.bind(window);
      window.setTimeout = (handler, timeout = 0, ...args) => (
        nativeSetTimeout(handler, Math.min(Number(timeout), 100), ...args)
      );
    });
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    return page;
  };
  try {
    const page = await preparePage();
    await page.goto(`http://127.0.0.1:${webAddress.port}/app/`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
    const environment = page.locator("#global-execution-domain");
    await environment.waitFor({ state: "visible", timeout: 3_000 });
    assert.equal(await environment.inputValue(), "");
    assert.match(await page.locator("#data-root-indicator").textContent(), /X:\\VIREA-DATA\\home/);
    assert.equal(await page.locator("[data-source-empty=true]").count(), 1);
    assert.equal(await page.locator("#source-skeleton-canvas").getAttribute("data-viewer-state"), "idle");
    assert.equal(await page.locator("#source-skeleton-canvas").getAttribute("data-source-frame"), "0");
    assert.equal(fakeJobRequestCount, 0, "bootstrap must not hydrate a test-only successful job");
    await environment.selectOption("wsl:Ubuntu-24.04");
    await page.locator('button[data-view="playground"]').click();
    await page.locator("#model-id").waitFor({ state: "visible", timeout: 3_000 });
    for (let attempt = 0; attempt < 30 && modelCatalogRequestCount < 2; attempt += 1) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 25));
    }
    assert.ok(
      modelCatalogRequestCount >= 2,
      "bootstrap must reconcile collections after its independently fetched revision checkpoint",
    );
    assert.equal(await page.locator("#model-id").inputValue(), "flood-diffusion-tiny");
    assert.equal(await page.locator("#global-execution-domain").inputValue(), "wsl:Ubuntu-24.04");
    assert.equal(systemRequestCount, 0, "bootstrap must not request the full system diagnostic");
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/execution-options")),
      page.locator("#model-id").dispatchEvent("change"),
    ]);
    assert.equal(executionOptionsRequestCount, 1);

    await page.evaluate(() => {
      window.__vireaStableCanvas = document.querySelector("#vrm-canvas");
    });
    assert.equal(
      await page.locator("#vrm-canvas").getAttribute("data-render-loop"),
      "running",
    );
    const clickStartedAt = Date.now();
    await page.locator("#generate").click();
    const immediateStatus = await page.locator("[data-generation-label]").textContent();
    assert.match(immediateStatus ?? "", /核验|提交/);
    assert.ok(Date.now() - clickStartedAt < 500, "Generate must paint feedback before the delayed POST returns");
    assert.equal(await page.locator("#generate").isDisabled(), true);
    assert.equal(
      await page.locator("#vrm-canvas").getAttribute("data-render-loop"),
      "stopped",
      "GPU rendering pauses while a generation owns the workbench",
    );
    await page.locator(".error").waitFor({ state: "visible", timeout: 3_000 });
    assert.equal(
      await page.locator("#vrm-canvas").getAttribute("data-render-loop"),
      "running",
      "the same Viewer resumes after generation without reimporting",
    );
    assert.equal(generationSubmitCount, 1);
    assert.equal(executionOptionsRequestCount, 2, "Generate must refresh target readiness before POST");
    assert.equal(typeof submittedGeneration?.idempotency_key, "string");
    assert.ok(submittedGeneration.idempotency_key.length > 8);
    assert.equal(
      await page.evaluate(() => window.__vireaStableCanvas === document.querySelector("#vrm-canvas")),
      true,
      "ordinary generation state changes must retain the WebGL canvas identity",
    );

    executionOptionsMode = "empty";
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/execution-options")),
      page.locator("#generate").click(),
    ]);
    await page.waitForFunction(
      () => document.querySelector(".error")?.textContent?.includes("没有返回"),
    );
    assert.equal(generationSubmitCount, 1, "an absent selected-domain option must not create a Job");

    executionOptionsMode = "error";
    await Promise.all([
      page.waitForResponse((response) => (
        response.url().endsWith("/execution-options") && response.status() === 503
      )),
      page.locator("#generate").click(),
    ]);
    await page.waitForFunction(
      () => document.querySelector(".error")?.textContent?.includes("503"),
    );
    assert.equal(generationSubmitCount, 1, "failed target discovery must not create a Job");
    executionOptionsMode = "valid";

    includeResponsiveJob = true;
    const recoveryPage = await preparePage();
    await recoveryPage.goto(`http://127.0.0.1:${webAddress.port}/app/`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
    await recoveryPage.locator("#generate").waitFor({ state: "visible", timeout: 3_000 });
    assert.equal(await recoveryPage.locator("#generate").isDisabled(), true);
    assert.match(await recoveryPage.locator("#generation-status").textContent(), /恢复|排队|QUEUED/);
    await recoveryPage.locator(".error").waitFor({ state: "visible", timeout: 3_000 });
    assert.equal(generationSubmitCount, 1, "reload must resume the durable Job instead of submitting another one");
    includeResponsiveJob = false;

    await page.locator('button[data-view="overview"]').click();
    await page.locator("#refresh").click();
    await page.locator(".error").waitFor({ state: "visible", timeout: 3_000 });
    assert.match(await page.locator(".error").textContent(), /GET \/api\/v1\/system timed out/);
    assert.equal(systemRequestCount, 1);
    assert.equal(executionDomainRequestCount, 3);
    assert.equal(await page.locator("#global-execution-domain").inputValue(), "wsl:Ubuntu-24.04");
    await page.locator('button[data-view="playground"]').click();
    await page.locator("#model-id").waitFor({ state: "visible", timeout: 3_000 });
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/execution-options")),
      page.locator("#model-id").dispatchEvent("change"),
    ]);
    assert.equal(executionOptionsRequestCount, 5, "refresh must clear execution-option cache");

    await page.locator('button[data-view="overview"]').click();
    await page.locator("#refresh").click();
    await page.waitForFunction(
      () => document.querySelector("#global-execution-domain")?.value === "windows-native",
    );
    assert.equal(systemRequestCount, 2);
    assert.equal(executionDomainRequestCount, 4);

    const deepPage = await preparePage();
    await deepPage.goto(`http://127.0.0.1:${webAddress.port}/app/?job=job-deep`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
    await deepPage.locator("#vrm-canvas").waitFor({ state: "visible", timeout: 3_000 });
    assert.match(await deepPage.locator(".viewer-readout").textContent(), /result-deep/);
    assert.equal(systemRequestCount, 2, "persisted deep-link bootstrap must not request /system");
    const expectedDiscoveryErrors = consoleErrors.filter((message) => (
      /Failed to load resource/.test(message) && /503 \(Service Unavailable\)/.test(message)
    ));
    assert.equal(expectedDiscoveryErrors.length, 1, "the deliberate 503 must remain visible to diagnostics");
    assert.deepEqual(
      consoleErrors.filter((message) => !expectedDiscoveryErrors.includes(message)),
      [],
    );
    assert.deepEqual(pageErrors, []);
  } finally {
    // Abort deliberately hung diagnostic responses before closing Chromium;
    // otherwise browser.close() can wait on the fixture's open HTTP socket
    // after an assertion failure and hide the actionable failure location.
    for (const socket of backendSockets) socket.destroy();
    const shutdownSession = browser.isConnected()
      ? await browser.newBrowserCDPSession()
      : null;
    const browserProcessId = shutdownSession
      ? (await shutdownSession.send("SystemInfo.getProcessInfo")).processInfo
        .find((entry) => entry.type === "browser")?.id
      : undefined;
    await shutdownSession?.detach();
    await Promise.all(
      browserContext.pages().map((openPage) => openPage.close({ runBeforeUnload: false })),
    );
    await browserContext.close();
    const gracefulClose = browser.close({ reason: "VIREA browser fixture complete" });
    if (!(await settlesWithin(gracefulClose, 3_000)) && browserProcessId) {
      // Chrome/SwiftShader on Windows can ignore graceful close after a
      // deliberately aborted proxy request. Terminate only the exact browser
      // PID obtained through that test instance's own CDP session.
      try {
        process.kill(browserProcessId, "SIGKILL");
      } catch (error) {
        if (error?.code !== "ESRCH") throw error;
      }
      await settlesWithin(gracefulClose, 3_000);
    }
    await vite.close();
    await new Promise((resolveClose) => backend.close(resolveClose));
  }
});


test("generation waits for authoritative VIREA_HOME and reconciles an ambiguous durable submit", {
  timeout: 30_000,
}, async (context) => {
  const executablePath = availableBrowserExecutable();
  if (!executablePath) {
    context.skip("no installed Chromium-family browser is available");
    return;
  }

  const homeA = "D:\\Private VIREA Data\\home-a";
  const homeB = "D:\\Private VIREA Data\\home-b";
  const homeC = "D:\\Private VIREA Data\\home-c";
  let authoritativeHome = homeA;
  const privatePrompt = "private prompt: walk toward the unreleased set";
  let stateReady = false;
  let stateRequestCount = 0;
  const stateResponsePlans = [];
  let switchHomeAfterOptions = "";
  let failStateAfterOptions = false;
  let executionOptionsRequestCount = 0;
  let modelRequestCount = 0;
  let modelResponseDelayMs = 0;
  let jobsReadable = true;
  let generationPostCount = 0;
  let durableJobCount = 0;
  let persistedJob = null;
  const backendSockets = new Set();
  const backend = createHttpServer((request, response) => {
    const path = new URL(request.url, "http://127.0.0.1").pathname;
    if (path === "/api/v1/health") {
      respondJson(response, {
        schema_version: "virea.health.v1.0.0",
        version: "0.4.0",
        status: "ready",
        control_plane_ready: true,
      });
      return;
    }
    if (path === "/api/v1/state") {
      stateRequestCount += 1;
      const plan = stateResponsePlans.shift();
      const sendState = () => {
        if (plan?.status === 503 || (!plan && !stateReady)) {
          respondJson(response, { detail: "authoritative state temporarily unavailable" }, 503);
          return;
        }
        respondJson(response, {
          schema_version: "virea.state_revision.v1.0.0",
          observed_at: new Date().toISOString(),
          events_url: "",
          virea_home: plan?.home ?? authoritativeHome,
          revision: {
            jobs: persistedJob ? "1:job-authority" : "0:",
            results: "0:",
            installations: "1:ready",
            models: "1:catalog",
            workers: "0::",
          },
        });
      };
      if (plan?.delayMs) setTimeout(sendState, plan.delayMs);
      else sendState();
      return;
    }
    if (path === "/api/v1/execution-domains") {
      respondJson(response, {
        schema_version: "virea.execution_domain_candidates.v1.0.0",
        report_id: "authority-domain-report",
        recorded_at: "2026-08-25T00:00:00Z",
        host_execution_domain: "windows-native",
        execution_domains: [{
          schema_version: "virea.execution_domain_report.v1.0.0",
          id: "windows-native",
          kind: "windows-native",
          platform: "win-64",
          architecture: "x86_64",
          is_host: true,
          distribution: null,
          warnings: [],
        }],
      });
      return;
    }
    if (path === "/api/v1/models/flood-diffusion-tiny/execution-options") {
      executionOptionsRequestCount += 1;
      if (switchHomeAfterOptions) {
        authoritativeHome = switchHomeAfterOptions;
        switchHomeAfterOptions = "";
      }
      if (failStateAfterOptions) {
        stateReady = false;
        failStateAfterOptions = false;
      }
      respondJson(response, {
        schema_version: "virea.model_execution_options.v1.0.0",
        model_id: "flood-diffusion-tiny",
        report_id: "authority-option-report",
        options: [{
          execution_domain: {
            schema_version: "virea.execution_domain_report.v1.0.0",
            id: "windows-native",
            kind: "windows-native",
            platform: "win-64",
            architecture: "x86_64",
            is_host: true,
            distribution: null,
            warnings: [],
          },
          implemented: true,
          selected_runtime_id: "flood-diffusion-tiny-cu128",
          status: "buildable",
          can_build: true,
          reasons: [],
          remediation: [],
          selected_resource_profile: "cuda-component-split",
          selected_memory_strategy: "cuda_component_split",
        }],
      });
      return;
    }
    if (path === "/api/v1/models") {
      modelRequestCount += 1;
      const delayMs = modelResponseDelayMs;
      if (delayMs) setTimeout(() => respondJson(response, [modelManifest()]), delayMs);
      else respondJson(response, [modelManifest()]);
      return;
    }
    if (path === "/api/v1/jobs" && request.method === "POST") {
      generationPostCount += 1;
      let body = "";
      request.on("data", (chunk) => { body += String(chunk); });
      request.on("end", () => {
        const payload = JSON.parse(body);
        if (!persistedJob) {
          durableJobCount += 1;
          persistedJob = {
            id: "job-authority",
            model_id: "flood-diffusion-tiny",
            task: "text_to_motion",
            state: "QUEUED",
            idempotency_key: payload.idempotency_key,
          };
        }
        // Commit succeeded, but the 202 body is deterministically impossible
        // to parse and immediate list reconciliation is unavailable. This is
        // the ambiguity window that must be recovered from durable state
        // without creating another Job.
        stateReady = false;
        jobsReadable = false;
        response.writeHead(202, { "content-type": "application/json" });
        response.end("{");
      });
      return;
    }
    if (path === "/api/v1/jobs") {
      if (!jobsReadable) {
        respondJson(response, { detail: "job reconciliation temporarily unavailable" }, 503);
        return;
      }
      respondJson(response, persistedJob ? [persistedJob] : []);
      return;
    }
    if (path === "/api/v1/jobs/job-authority") {
      respondJson(response, {
        ...persistedJob,
        state: "FAILED",
        error_code: "EXPECTED_AMBIGUOUS_SUBMIT_STOP",
        error_message: "fixture ends after durable reconciliation",
      });
      return;
    }
    respondJson(response, { detail: `unhandled test path ${path}` }, 404);
  });
  backend.on("connection", (socket) => {
    backendSockets.add(socket);
    socket.once("close", () => backendSockets.delete(socket));
  });

  let vite = null;
  let browser = null;
  let browserContext = null;
  try {
    await new Promise((resolveListen) => backend.listen({
      host: "127.0.0.1",
      port: 0,
      exclusive: true,
    }, resolveListen));
    const backendAddress = backend.address();
    assert.equal(typeof backendAddress, "object");
    vite = await createViteServer({
      root: WEB_ROOT,
      logLevel: "silent",
      server: {
        host: "127.0.0.1",
        port: 0,
        strictPort: false,
        proxy: { "/api": `http://127.0.0.1:${backendAddress.port}` },
      },
    });
    await vite.listen();
    const webAddress = vite.httpServer?.address();
    assert.equal(typeof webAddress, "object");
    browser = await chromium.launch({
      executablePath,
      headless: true,
      args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    });
    browserContext = await browser.newContext({ viewport: { width: 1_280, height: 900 } });
    const page = await browserContext.newPage();
    page.setDefaultTimeout(3_000);
    await page.routeWebSocket(/\/api\/v1\/jobs\/[^/]+\/events$/, (socket) => socket.close());
    await page.goto(`http://127.0.0.1:${webAddress.port}/app/`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });

    const generate = page.locator("#generate");
    await generate.waitFor({ state: "visible", timeout: 3_000 });
    await page.locator("#prompt").fill(privatePrompt);
    assert.equal(await generate.isDisabled(), true, "missing authoritative home must fail closed");
    assert.match(await generate.textContent(), /等待数据根同步/);
    await generate.dispatchEvent("click");
    await page.waitForFunction(() => document.querySelector(".error")?.textContent?.includes("VIREA_HOME"));
    assert.equal(generationPostCount, 0, "generate() itself must reject an event bypassing disabled UI");

    stateReady = true;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => !document.querySelector("#generate")?.disabled);
    assert.match(await page.locator("#data-root-indicator").textContent(), /Private VIREA Data/);

    stateReady = false;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 503),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => document.querySelector("#generate")?.disabled);
    assert.match(await page.locator("#data-root-indicator").textContent(), /home-a.*待确认|待确认.*home-a/);
    await page.evaluate(() => document.querySelector("#generate")?.click());
    await generate.dispatchEvent("click");
    assert.equal(generationPostCount, 0, "normal and forced activation must fail closed while authority is stale");
    assert.equal(executionOptionsRequestCount, 0, "stale authority must fail before target discovery");

    authoritativeHome = homeB;
    await generate.dispatchEvent("click");
    assert.equal(generationPostCount, 0, "a hidden server-side root switch cannot use stale home A");
    stateReady = true;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => !document.querySelector("#generate")?.disabled);
    assert.match(await page.locator("#data-root-indicator").textContent(), /home-b/);
    assert.doesNotMatch(await page.locator("#data-root-indicator").textContent(), /待确认/);

    // A late failure from an older /state request must not invalidate a newer
    // successful authority observation.
    stateResponsePlans.push(
      { status: 503, delayMs: 250 },
      { status: 200, delayMs: 0, home: homeB },
    );
    const stateCountBeforeRace = stateRequestCount;
    const staleResponse = page.waitForResponse(
      (item) => item.url().endsWith("/api/v1/state") && item.status() === 503,
    );
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    for (let attempt = 0; attempt < 50 && stateRequestCount === stateCountBeforeRace; attempt += 1) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 10));
    }
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await staleResponse;
    assert.equal(await generate.isDisabled(), false, "superseded failure must not stale newer authority");
    assert.doesNotMatch(await page.locator("#data-root-indicator").textContent(), /待确认/);

    failStateAfterOptions = true;
    await generate.click();
    await page.waitForFunction(() => document.querySelector(".error")?.textContent?.includes("提交前无法重新确认"));
    assert.equal(generationPostCount, 0, "failed pre-POST authority refresh must not create a Job");
    assert.match(await page.locator("#data-root-indicator").textContent(), /home-b.*待确认|待确认.*home-b/);
    stateReady = true;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => !document.querySelector("#generate")?.disabled);

    // Execution options can still be valid after a root switch. The explicit
    // pre-POST authority read must apply home C and require a retry, with 0 POST.
    switchHomeAfterOptions = homeC;
    await generate.click();
    await page.waitForFunction(() => document.querySelector(".error")?.textContent?.includes("已应用最新状态"));
    assert.equal(generationPostCount, 0, "pre-POST A/B authority mismatch must not create a Job");
    assert.match(await page.locator("#data-root-indicator").textContent(), /home-c/);
    assert.match(await page.locator("#data-root-indicator").textContent(), /待确认/);
    assert.equal(await generate.isDisabled(), true, "new root stays stale until its collections reconcile");
    modelResponseDelayMs = 250;
    const modelCountBeforeReconciliation = modelRequestCount;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    for (
      let attempt = 0;
      attempt < 50 && modelRequestCount === modelCountBeforeReconciliation;
      attempt += 1
    ) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 10));
    }
    stateReady = false;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 503),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await new Promise((resolveWait) => setTimeout(resolveWait, 300));
    assert.equal(
      await generate.isDisabled(),
      true,
      "collections from an older authority observation cannot restore freshness after /state failed",
    );
    assert.match(await page.locator("#data-root-indicator").textContent(), /待确认/);
    assert.match(await page.locator("#sync-status").textContent(), /连接中断/);
    modelResponseDelayMs = 0;
    stateReady = true;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => !document.querySelector("#generate")?.disabled);

    await generate.click();
    await page.waitForFunction(() => {
      const message = document.querySelector(".error")?.textContent ?? "";
      return Boolean(message) && !message.includes("已应用最新状态");
    });
    assert.equal(generationPostCount, 1);
    assert.equal(durableJobCount, 1);
    const pendingStorage = await page.evaluate(() => (
      window.localStorage.getItem("virea.pending-generation.v1")
    ));
    assert.ok(pendingStorage, "ambiguous submission identity must survive until durable reconciliation");
    const pendingPayload = JSON.parse(pendingStorage);
    assert.match(pendingPayload.fingerprint, /^sha256:[0-9a-f]{64}$/);
    assert.equal(pendingStorage.includes(privatePrompt), false);
    assert.equal(pendingStorage.includes(authoritativeHome), false);

    stateReady = true;
    jobsReadable = true;
    await Promise.all([
      page.waitForResponse((item) => item.url().endsWith("/api/v1/state") && item.status() === 200),
      page.evaluate(() => window.dispatchEvent(new Event("online"))),
    ]);
    await page.waitForFunction(() => (
      window.localStorage.getItem("virea.pending-generation.v1") === null
    ));
    await page.waitForFunction(() => (
      document.querySelector(".error")?.textContent?.includes("EXPECTED_AMBIGUOUS_SUBMIT_STOP")
    ));
    await new Promise((resolveWait) => setTimeout(resolveWait, 150));
    assert.equal(generationPostCount, 1, "state recovery must resume the durable Job without a second POST");
    assert.equal(durableJobCount, 1, "state recovery must not create a second Job");
  } finally {
    for (const socket of backendSockets) socket.destroy();
    let browserProcessId;
    if (browser?.isConnected()) {
      const shutdownSession = await browser.newBrowserCDPSession();
      browserProcessId = (await shutdownSession.send("SystemInfo.getProcessInfo")).processInfo
        .find((entry) => entry.type === "browser")?.id;
      await shutdownSession.detach();
    }
    if (browserContext) {
      await Promise.all(
        browserContext.pages().map((page) => page.close({ runBeforeUnload: false })),
      );
      await browserContext.close();
    }
    if (browser) {
      const gracefulClose = browser.close({ reason: "VIREA authority fixture complete" });
      if (!(await settlesWithin(gracefulClose, 3_000)) && browserProcessId) {
        try {
          process.kill(browserProcessId, "SIGKILL");
        } catch (error) {
          if (error?.code !== "ESRCH") throw error;
        }
        await settlesWithin(gracefulClose, 3_000);
      }
    }
    if (vite) await vite.close();
    if (backend.listening) await new Promise((resolveClose) => backend.close(resolveClose));
  }
});
