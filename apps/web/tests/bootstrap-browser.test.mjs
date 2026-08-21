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


test("a hung explicit system diagnostic cannot block bootstrap, Playground, or a persisted deep link", {
  timeout: 20_000,
}, async (context) => {
  const executablePath = availableBrowserExecutable();
  if (!executablePath) {
    context.skip("no installed Chromium-family browser is available");
    return;
  }
  let systemRequestCount = 0;
  let executionDomainRequestCount = 0;
  let executionOptionsRequestCount = 0;
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
    if (path === "/api/v1/execution-domains") {
      executionDomainRequestCount += 1;
      const includeWsl = executionDomainRequestCount <= 2;
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
      respondJson(response, {
        schema_version: "virea.model_execution_options.v1.0.0",
        model_id: "flood-diffusion-tiny",
        options: [],
      });
      return;
    }
    if (path === "/api/v1/models") {
      respondJson(response, [modelManifest()]);
      return;
    }
    if (path === "/api/v1/jobs") {
      respondJson(response, []);
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
      // WSL, and accelerators.  Keep this request pending until the browser's
      // bounded client cancels it.
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
    await environment.selectOption("wsl:Ubuntu-24.04");
    await page.locator('button[data-view="playground"]').click();
    await page.locator("#model-id").waitFor({ state: "visible", timeout: 3_000 });
    assert.equal(await page.locator("#model-id").inputValue(), "flood-diffusion-tiny");
    assert.equal(await page.locator("#global-execution-domain").inputValue(), "wsl:Ubuntu-24.04");
    assert.equal(systemRequestCount, 0, "bootstrap must not request the full system diagnostic");
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/execution-options")),
      page.locator("#model-id").dispatchEvent("change"),
    ]);
    assert.equal(executionOptionsRequestCount, 1);

    await page.locator('button[data-view="overview"]').click();
    await page.locator("#refresh").click();
    await page.locator(".error").waitFor({ state: "visible", timeout: 3_000 });
    assert.match(await page.locator(".error").textContent(), /GET \/api\/v1\/system timed out/);
    assert.equal(systemRequestCount, 1);
    assert.equal(executionDomainRequestCount, 2);
    assert.equal(await page.locator("#global-execution-domain").inputValue(), "wsl:Ubuntu-24.04");
    await page.locator('button[data-view="playground"]').click();
    await page.locator("#model-id").waitFor({ state: "visible", timeout: 3_000 });
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/execution-options")),
      page.locator("#model-id").dispatchEvent("change"),
    ]);
    assert.equal(executionOptionsRequestCount, 2, "refresh must clear execution-option cache");

    await page.locator('button[data-view="overview"]').click();
    await page.locator("#refresh").click();
    await page.waitForFunction(
      () => document.querySelector("#global-execution-domain")?.value === "windows-native",
    );
    assert.equal(systemRequestCount, 2);
    assert.equal(executionDomainRequestCount, 3);

    const deepPage = await preparePage();
    await deepPage.goto(`http://127.0.0.1:${webAddress.port}/app/?job=job-deep`, {
      waitUntil: "domcontentloaded",
      timeout: 10_000,
    });
    await deepPage.locator("#vrm-canvas").waitFor({ state: "visible", timeout: 3_000 });
    assert.match(await deepPage.locator(".viewer-readout").textContent(), /result-deep/);
    assert.equal(systemRequestCount, 2, "persisted deep-link bootstrap must not request /system");
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(pageErrors, []);
  } finally {
    await browser.close();
    await vite.close();
    for (const socket of backendSockets) socket.destroy();
    await new Promise((resolveClose) => backend.close(resolveClose));
  }
});
