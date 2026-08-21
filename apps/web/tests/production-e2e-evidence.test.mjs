import test from "node:test";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { EventEmitter } from "node:events";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createServer as createHttpServer } from "node:http";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { performance } from "node:perf_hooks";

import {
  acceptanceDefaults,
  applicationJavascriptHttpGetObservation,
  assertPortablePayload,
  assertExternalPath,
  buildManagedApiLifecycle,
  buildBrowserObservation,
  evidenceLocator,
  portableDiagnosticPayload,
  portableHomePayload,
  portableHomeText,
  projectedBounds,
  resultArtifactUrlPath,
  stopManagedApi,
  waitForApiHealth,
  waitForLoopbackPortClosed,
  vrmaHttpGetObservation,
} from "../../../scripts/lib/production-e2e-evidence.mjs";

const RUNNER_PATH = resolve(
  import.meta.dirname,
  "../../../scripts/run_production_browser_e2e.mjs",
);


function runChild(executable, args, { timeoutMs = 10_000 } = {}) {
  return new Promise((resolveChild, rejectChild) => {
    const child = spawn(executable, args, {
      encoding: "utf8",
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      rejectChild(new Error(`child did not exit within ${timeoutMs} ms`));
    }, timeoutMs);
    child.once("error", (error) => {
      clearTimeout(timer);
      rejectChild(error);
    });
    child.once("close", (code, signal) => {
      clearTimeout(timer);
      resolveChild({ code, signal, stdout: stdout.join(""), stderr: stderr.join("") });
    });
  });
}


class FakeManagedApi extends EventEmitter {
  constructor({ exitOnEof }) {
    super();
    this.exitCode = null;
    this.signalCode = null;
    this.ended = false;
    this.kills = [];
    this.stdin = {
      destroyed: false,
      end: () => {
        this.ended = true;
        if (exitOnEof) {
          queueMicrotask(() => {
            this.exitCode = 0;
            this.emit("exit", 0, null);
          });
        }
      },
    };
  }

  kill(signal) {
    this.kills.push(signal);
    this.signalCode = signal;
    this.emit("exit", null, signal);
    return true;
  }
}


test("managed API closes stdin and waits for normal lifespan shutdown before force fallback", async () => {
  const graceful = new FakeManagedApi({ exitOnEof: true });
  assert.deepEqual(await stopManagedApi(graceful, { gracefulTimeoutMs: 20, forceTimeoutMs: 20 }), {
    stdin_eof_requested: true,
    graceful: true,
    forced: false,
    exit_code: 0,
    exit_signal: null,
  });
  assert.equal(graceful.ended, true);
  assert.deepEqual(graceful.kills, []);

  const stuck = new FakeManagedApi({ exitOnEof: false });
  assert.deepEqual(await stopManagedApi(stuck, { gracefulTimeoutMs: 1, forceTimeoutMs: 20 }), {
    stdin_eof_requested: true,
    graceful: false,
    forced: true,
    exit_code: null,
    exit_signal: "SIGTERM",
  });
  assert.equal(stuck.ended, true);
  assert.deepEqual(stuck.kills, ["SIGTERM"]);
});


test("managed API stop does not throw again after an asynchronous spawn failure", async () => {
  const failedSpawn = new EventEmitter();
  failedSpawn.exitCode = null;
  failedSpawn.signalCode = null;
  failedSpawn.stdin = { destroyed: true };
  failedSpawn.kill = () => {
    throw new Error("no operating-system process exists");
  };
  assert.deepEqual(await stopManagedApi(
    failedSpawn,
    { gracefulTimeoutMs: 0, forceTimeoutMs: 0 },
  ), {
    stdin_eof_requested: false,
    graceful: false,
    forced: false,
    exit_code: null,
    exit_signal: null,
  });
});


test("managed API lifecycle records the cooperative exit and closed loopback port", async () => {
  const probes = ["open", "unknown", "closed"];
  assert.equal(await waitForLoopbackPortClosed({
    host: "127.0.0.1",
    port: 8819,
    timeoutMs: 100,
    pollMs: 0,
    probe: async () => probes.shift(),
    bindProbe: async () => "in_use",
  }), "connection_refused");
  assert.deepEqual(buildManagedApiLifecycle({
    managed: true,
    processSpawned: true,
    startedAt: "2026-08-21T01:00:00.000Z",
    stoppedAt: "2026-08-21T01:01:00.000Z",
    pid: 4321,
    loopbackPort: 8819,
    shutdown: {
      stdin_eof_requested: true,
      graceful: true,
      forced: false,
      exit_code: 0,
      exit_signal: null,
    },
    portCloseMethod: "connection_refused",
  }), {
    schema_version: "virea.managed_api_lifecycle.v1.0.0",
    managed: true,
    process_spawned: true,
    started_at: "2026-08-21T01:00:00.000Z",
    stopped_at: "2026-08-21T01:01:00.000Z",
    pid: 4321,
    loopback_port: 8819,
    stdin_eof_requested: true,
    graceful: true,
    forced: false,
    exit_code: 0,
    exit_signal: null,
    port_closed: true,
    port_close_method: "connection_refused",
  });
});


test("managed API port closure never treats timeout or unknown socket errors as closed", async () => {
  for (const [state, bindState] of [["open", "available"], ["unknown", "in_use"], ["unknown", "unknown"]]) {
    assert.equal(await waitForLoopbackPortClosed({
      host: "127.0.0.1",
      port: 8819,
      timeoutMs: 0,
      pollMs: 0,
      probe: async () => state,
      bindProbe: async () => bindState,
    }), null);
  }
});


test("timeout plus exact-host exclusive bind availability is a distinct closed fact", async () => {
  const observed = [];
  assert.equal(await waitForLoopbackPortClosed({
    host: "127.0.0.1",
    port: 8819,
    timeoutMs: 0,
    pollMs: 0,
    probe: async () => "unknown",
    bindProbe: async (host, port) => {
      observed.push([host, port]);
      return "available";
    },
  }), "exclusive_bind_available");
  assert.deepEqual(observed, [["127.0.0.1", 8819]]);
});


test("a live exact IPv4 listener prevents the exclusive-bind closed fact", async () => {
  const server = createServer();
  await new Promise((resolveListen) => server.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const address = server.address();
  assert.equal(typeof address, "object");
  try {
    assert.equal(await waitForLoopbackPortClosed({
      host: "127.0.0.1",
      port: address.port,
      timeoutMs: 0,
      pollMs: 0,
      probe: async () => "unknown",
    }), null);
  } finally {
    await new Promise((resolveClose) => server.close(resolveClose));
  }
});


test("health readiness aborts a hung HTTP response at the monotonic total deadline", async () => {
  let requestCount = 0;
  let activeRequests = 0;
  let maximumActiveRequests = 0;
  const sockets = new Set();
  const server = createHttpServer((request) => {
    requestCount += 1;
    activeRequests += 1;
    maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
    request.once("close", () => {
      activeRequests -= 1;
    });
    // Intentionally accept the HTTP request without sending headers or a body.
  });
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  await new Promise((resolveListen) => server.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const address = server.address();
  assert.equal(typeof address, "object");
  const started = performance.now();
  try {
    await assert.rejects(
      waitForApiHealth(`http://127.0.0.1:${address.port}`, {
        timeoutMs: 180,
        attemptTimeoutMs: 70,
        pollMs: 15,
      }),
      /did not become ready within 180 ms.*timed out/s,
    );
    const elapsed = performance.now() - started;
    assert.ok(elapsed >= 150, `deadline fired too early after ${elapsed} ms`);
    assert.ok(elapsed < 800, `hung readiness exceeded its hard bound: ${elapsed} ms`);
    assert.ok(requestCount >= 1 && requestCount <= 3, `unexpected probe count ${requestCount}`);
    assert.equal(maximumActiveRequests, 1);
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise((resolveClose) => server.close(resolveClose));
  }
});


test("health readiness recovers after one bounded slow response without overlapping probes", async () => {
  let requestCount = 0;
  let activeRequests = 0;
  let maximumActiveRequests = 0;
  const sockets = new Set();
  const server = createHttpServer((request, response) => {
    requestCount += 1;
    activeRequests += 1;
    maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
    request.once("close", () => {
      activeRequests -= 1;
    });
    if (requestCount === 1) return;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({
      schema_version: "virea.health.v1.0.0",
      version: "0.4.0",
      status: "ready",
      control_plane_ready: true,
    }));
  });
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  await new Promise((resolveListen) => server.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const address = server.address();
  assert.equal(typeof address, "object");
  try {
    const health = await waitForApiHealth(`http://127.0.0.1:${address.port}`, {
      timeoutMs: 1_000,
      attemptTimeoutMs: 70,
      pollMs: 10,
    });
    assert.deepEqual(health, {
      schema_version: "virea.health.v1.0.0",
      version: "0.4.0",
      status: "ready",
      control_plane_ready: true,
    });
    assert.equal(requestCount, 2);
    assert.equal(maximumActiveRequests, 1);
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise((resolveClose) => server.close(resolveClose));
  }
});


test("production runner starts the API with a piped EOF shutdown channel", () => {
  const source = readFileSync(RUNNER_PATH, "utf8");
  assert.match(source, /"--shutdown-on-stdin-eof"/);
  assert.match(source, /stdio:\s*\["pipe", stdoutFd, stderrFd\]/);
  assert.match(source, /return stopManagedApi\(serverProcess\)/);
  assert.match(source, /"managed-api-lifecycle\.json"/);
  assert.match(source, /waitForLoopbackPortClosed/);
  assert.match(source, /flag:\s*"wx"/);
  assert.match(source, /serverProcess\.once\("error"/);
  assert.match(source, /Number\.isSafeInteger\(lifecycle\.pid\)/);
  assert.match(source, /waitForApiHealth/);
  assert.doesNotMatch(source, /apiJson\("\/api\/v1\/system"\)/);
});


test("a hung external readiness listener yields bounded portable diagnostics without being killed", async () => {
  const root = mkdtempSync(join(tmpdir(), "virea-health-readiness-timeout-"));
  const home = join(root, "private-home");
  const output = join(root, "evidence");
  const avatar = join(root, "Seed-san.vrm");
  mkdirSync(home);
  writeFileSync(avatar, "test-vrm", "utf8");
  let requestCount = 0;
  let activeRequests = 0;
  let maximumActiveRequests = 0;
  const sockets = new Set();
  const server = createHttpServer((request) => {
    requestCount += 1;
    activeRequests += 1;
    maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
    request.once("close", () => {
      activeRequests -= 1;
    });
  });
  server.on("connection", (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
  });
  await new Promise((resolveListen) => server.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const address = server.address();
  assert.equal(typeof address, "object");
  const started = performance.now();
  try {
    const completed = await runChild(process.execPath, [
      RUNNER_PATH,
      "--model-id", "flood-diffusion-tiny",
      "--output-dir", output,
      "--vrm", avatar,
      "--vrm-usage-basis", "test-only local asset",
      "--base-url", `http://127.0.0.1:${address.port}`,
      "--virea-home", home,
      "--api-readiness-timeout-ms", "350",
      "--api-readiness-attempt-timeout-ms", "100",
    ]);
    const elapsed = performance.now() - started;
    assert.equal(completed.code, 2, completed.stderr);
    assert.equal(completed.signal, null);
    assert.ok(elapsed < 3_000, `runner exceeded the bounded readiness failure: ${elapsed} ms`);
    assert.equal(server.listening, true);
    assert.ok(requestCount >= 1 && requestCount <= 3, `unexpected probe count ${requestCount}`);
    assert.equal(maximumActiveRequests, 1);

    const failure = JSON.parse(readFileSync(join(output, "browser-e2e-failure.json"), "utf8"));
    const lifecycle = JSON.parse(readFileSync(
      join(output, "managed-api-lifecycle.json"),
      "utf8",
    ));
    assert.equal(failure.failure.stage, "managed_api_startup");
    assert.match(failure.failure.message, /did not become ready within 350 ms.*timed out/s);
    assert.equal(failure.eligible_for_promotion, false);
    assert.deepEqual(lifecycle, {
      schema_version: "virea.managed_api_lifecycle.v1.0.0",
      managed: false,
      process_spawned: false,
      started_at: lifecycle.started_at,
      stopped_at: lifecycle.stopped_at,
      pid: null,
      loopback_port: address.port,
      stdin_eof_requested: false,
      graceful: false,
      forced: false,
      exit_code: null,
      exit_signal: null,
      port_closed: false,
      port_close_method: null,
    });
    assert.doesNotThrow(() => assertPortablePayload({ failure, lifecycle }, "hung readiness"));
    const serialized = JSON.stringify({ failure, lifecycle });
    assert.equal(serialized.includes(root), false);
    assert.equal(serialized.includes(root.replaceAll("\\", "/")), false);
    assert.equal(existsSync(join(home, "state", "virea.db")), false);
  } finally {
    for (const socket of sockets) socket.destroy();
    await new Promise((resolveClose) => server.close(resolveClose));
    rmSync(root, { recursive: true, force: true });
  }
});


test("invalid managed API executable still writes portable failure and lifecycle evidence", async () => {
  const root = mkdtempSync(join(tmpdir(), "virea-managed-api-spawn-failure-"));
  const home = join(root, "private-home");
  const output = join(root, "evidence");
  const avatar = join(root, "Seed-san.vrm");
  const missingPython = join(root, "missing-python.exe");
  mkdirSync(home);
  writeFileSync(avatar, "test-vrm", "utf8");
  const reservation = createServer();
  await new Promise((resolveListen) => reservation.listen({
    host: "127.0.0.1",
    port: 0,
    exclusive: true,
  }, resolveListen));
  const reservedAddress = reservation.address();
  assert.equal(typeof reservedAddress, "object");
  const port = reservedAddress.port;
  await new Promise((resolveClose) => reservation.close(resolveClose));
  try {
    const completed = spawnSync(process.execPath, [
      RUNNER_PATH,
      "--model-id", "flood-diffusion-tiny",
      "--output-dir", output,
      "--vrm", avatar,
      "--vrm-usage-basis", "test-only local asset",
      "--base-url", `http://127.0.0.1:${port}`,
      "--virea-home", home,
      "--python", missingPython,
      "--start-api",
    ], {
      encoding: "utf8",
      timeout: 15_000,
      windowsHide: true,
    });
    assert.equal(completed.error, undefined);
    assert.equal(completed.status, 2, completed.stderr);
    const lifecycle = JSON.parse(readFileSync(
      join(output, "managed-api-lifecycle.json"),
      "utf8",
    ));
    assert.deepEqual(lifecycle, {
      schema_version: "virea.managed_api_lifecycle.v1.0.0",
      managed: true,
      process_spawned: false,
      started_at: lifecycle.started_at,
      stopped_at: lifecycle.stopped_at,
      pid: null,
      loopback_port: port,
      stdin_eof_requested: false,
      graceful: false,
      forced: false,
      exit_code: null,
      exit_signal: null,
      port_closed: false,
      port_close_method: null,
    });
    const failure = JSON.parse(readFileSync(join(output, "browser-e2e-failure.json"), "utf8"));
    assert.equal(failure.failure.type, "Error");
    assert.equal(failure.failure.stage, "managed_api_startup");
    assert.equal(failure.eligible_for_promotion, false);
    assert.doesNotThrow(() => assertPortablePayload(failure, "failure"));
    const serialized = JSON.stringify({ lifecycle, failure });
    assert.equal(serialized.includes(root), false);
    assert.equal(serialized.includes(root.replaceAll("\\", "/")), false);
    assert.equal(existsSync(join(home, "state", "virea.db")), false);

    const proof = createServer();
    await new Promise((resolveListen) => proof.listen({
      host: "127.0.0.1",
      port,
      exclusive: true,
    }, resolveListen));
    await new Promise((resolveClose) => proof.close(resolveClose));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});


test("runner failure payload replaces known Windows and WSL homes without weakening diagnostics", () => {
  assert.equal(
    portableHomeText(
      "failed under D:/Users/alice/virea-home/results/result-1 and D:\\Users\\alice\\virea-home\\state",
      "D:\\Users\\alice\\virea-home",
    ),
    "failed under ${VIREA_HOME}/results/result-1 and ${VIREA_HOME}/state",
  );
  assert.deepEqual(
    portableHomePayload(
      { message: "failed at /home/alice/.local/share/virea/results/result-1", nested: ["safe"] },
      "/home/alice/.local/share/virea",
    ),
    { message: "failed at ${VIREA_HOME}/results/result-1", nested: ["safe"] },
  );
});


test("failure diagnostics preserve type and stage but scrub every local absolute path", () => {
  const diagnostic = portableDiagnosticPayload({
    failure: {
      type: "RuntimeError",
      stage: "viewer_playback",
      message: "failed in D:\\source\\virea for D:\\qa\\Seed-san.vrm",
    },
    console: [
      "worker at /home/alice/.local/share/virea/results/result-1",
      "plugin at /opt/private/plugin/runtime.py",
    ],
  }, {
    home: "/home/alice/.local/share/virea",
    knownPaths: [
      { path: "D:\\source\\virea", token: "${CHECKOUT}" },
      { path: "D:\\qa\\Seed-san.vrm", token: "${VRM_ASSET}/Seed-san.vrm" },
    ],
  });
  assert.equal(diagnostic.failure.type, "RuntimeError");
  assert.equal(diagnostic.failure.stage, "viewer_playback");
  assert.equal(
    diagnostic.failure.message,
    "failed in ${CHECKOUT} for ${VRM_ASSET}/Seed-san.vrm",
  );
  assert.equal(diagnostic.console[0], "worker at ${VIREA_HOME}/results/result-1");
  assert.equal(diagnostic.console[1], "local path detail redacted");
  assert.doesNotThrow(() => assertPortablePayload(diagnostic, "failure"));
  assert.throws(
    () => assertPortablePayload({ message: "/root/private/runtime.py" }, "failure"),
    /non-portable local absolute path/,
  );
});


function prismManifest() {
  return {
    model: { id: "prism-tp2m-1-4b" },
    production_acceptance: {
      request: {
        schema_version: "virea.job_request.v1.0.0",
        model_id: "prism-tp2m-1-4b",
        task: "text_to_motion",
        input: { prompt: "A person walks.", motion_length_frames: 129 },
        parameters: { fps: 30, seed: 42, num_inference_steps: 50, guidance_scale: 5 },
        avatar_id: null,
        idempotency_key: null,
      },
    },
  };
}


test("browser runner derives PRISM's exact acceptance duration without rewriting the request", () => {
  const manifest = prismManifest();
  const defaults = acceptanceDefaults(manifest);

  assert.equal(defaults.seconds, 4.3);
  assert.equal(defaults.fps, 30);
  assert.equal(defaults.seed, 42);
  assert.deepEqual(defaults.request, manifest.production_acceptance.request);
});


test("production evidence refuses checkout output and traversal locators", () => {
  const checkout = resolve("D:/source/virea");
  assert.throws(() => assertExternalPath(resolve(checkout, "evidence"), checkout, "output"), /outside/);
  assert.equal(
    assertExternalPath(resolve("D:/virea-data/evidence"), checkout, "output"),
    resolve("D:/virea-data/evidence"),
  );
  assert.throws(() => evidenceLocator("../viewer.png"), /clean relative path/);
  assert.throws(() => evidenceLocator("D:/viewer.png"), /clean relative path/);
});


test("projected bounds translate Viewer camelCase telemetry into the public contract", () => {
  assert.deepEqual(
    projectedBounds('{"minX":-0.4,"minY":-0.8,"minZ":0.1,"maxX":0.4,"maxY":0.8,"maxZ":0.5}'),
    { min_x: -0.4, min_y: -0.8, min_z: 0.1, max_x: 0.4, max_y: 0.8, max_z: 0.5 },
  );
  assert.throws(() => projectedBounds("{}"), /finite projected avatar bounds/);
});


function vrmaNetworkObservation({
  requestUrl = "http://127.0.0.1:8000/api/v1/results/result-1/artifacts/actor-0.vrma",
  responseUrl = requestUrl,
  bodyByteLength = 4096,
  contentLength = 4096,
} = {}) {
  return vrmaHttpGetObservation({
    baseUrl: "http://127.0.0.1:8000",
    resultId: "result-1",
    locator: "results/result-1/actor-0.vrma",
    byteLength: 4096,
    requests: [{ url: requestUrl, method: "GET" }],
    responses: [{
      url: responseUrl,
      method: "GET",
      status: 200,
      bodyByteLength,
      contentLength,
    }],
  });
}


function applicationNetworkObservation({
  requestUrl = "http://127.0.0.1:8000/app/assets/index-Blj3frjw.js",
  responseUrl = requestUrl,
  bodyByteLength = 791886,
  contentLength = 791886,
} = {}) {
  return applicationJavascriptHttpGetObservation({
    requests: [{ url: requestUrl, method: "GET" }],
    responses: [{
      url: responseUrl,
      method: "GET",
      status: 200,
      bodyByteLength,
      contentLength,
    }],
  });
}


test("application binding records one exact hashed JavaScript GET/200 response body", () => {
  assert.deepEqual(applicationNetworkObservation(), {
    url_path: "/app/assets/index-Blj3frjw.js",
    method: "GET",
    status: 200,
    body_byte_length: 791886,
    content_length: 791886,
    unique_request_count: 1,
    unique_response_count: 1,
  });
});


test("application binding rejects stale, duplicate, and mismatched JavaScript responses", () => {
  assert.throws(
    () => applicationNetworkObservation({
      responseUrl: "http://127.0.0.1:8000/app/assets/index-stale030.js",
    }),
    /request and response URLs differ/,
  );
  assert.throws(
    () => applicationNetworkObservation({ contentLength: 791885 }),
    /Content-Length differs/,
  );
  assert.throws(
    () => applicationJavascriptHttpGetObservation({
      requests: [
        { url: "http://127.0.0.1:8000/app/assets/index-one.js", method: "GET" },
        { url: "http://127.0.0.1:8000/app/assets/index-two.js", method: "GET" },
      ],
      responses: [],
    }),
    /exactly one hashed application JavaScript request/,
  );
});


test("VRMA browser binding records one exact GET/200 response body", () => {
  assert.equal(
    resultArtifactUrlPath("result 1", "results/result 1/actor 0.vrma"),
    "/api/v1/results/result%201/artifacts/actor%200.vrma",
  );
  assert.deepEqual(vrmaNetworkObservation(), {
    url_path: "/api/v1/results/result-1/artifacts/actor-0.vrma",
    method: "GET",
    status: 200,
    body_byte_length: 4096,
    content_length: 4096,
    unique_request_count: 1,
    unique_response_count: 1,
  });
});


test("VRMA browser binding rejects wrong and stale artifact URLs", () => {
  assert.throws(
    () => vrmaNetworkObservation({
      requestUrl: "http://127.0.0.1:8000/api/v1/results/result-1/artifacts/wrong.vrma",
    }),
    /URL differs from the current result artifact URL/,
  );
  assert.throws(
    () => vrmaNetworkObservation({
      requestUrl: "http://127.0.0.1:8000/api/v1/results/stale-result/artifacts/actor-0.vrma",
    }),
    /URL differs from the current result artifact URL/,
  );
});


test("VRMA browser binding rejects body and Content-Length mismatches", () => {
  assert.throws(
    () => vrmaNetworkObservation({ bodyByteLength: 4095, contentLength: 4095 }),
    /response body length differs/,
  );
  assert.throws(
    () => vrmaNetworkObservation({ contentLength: 4095 }),
    /Content-Length differs/,
  );
});


test("raw browser observation has no promotion field or client certification path", () => {
  const request = prismManifest().production_acceptance.request;
  const observation = buildBrowserObservation({
    runId: "browser-prism-1",
    startedAt: "2026-08-21T01:00:00Z",
    completedAt: "2026-08-21T01:10:00Z",
    generationMode: "fresh_web_job",
    baseUrl: "http://127.0.0.1:8000",
    application: {
      application_version: "0.4.0",
      visible_version_label: "Motion Studio 0.4.0",
      javascript: applicationNetworkObservation(),
    },
    manifest: prismManifest(),
    request,
    job: { id: "job-1", state: "SUCCEEDED" },
    modelResult: {
      model: {
        id: "prism-tp2m-1-4b",
        plugin_version: "0.1.0",
        upstream_revision: "revision-1",
        runtime_id: "prism-runtime",
      },
      native: { frame_count: 129 },
    },
    result: {
      result_id: "result-1",
      job_id: "job-1",
      identity: {
        model_id: "prism-tp2m-1-4b",
        model_version: "0.1.0",
        runtime_variant_id: "prism-runtime",
        checkpoint_revision: "revision-1",
        native_representation_id: "prism.smplh_body22.axis_angle69.v1",
        native_skeleton_id: "smplh.body22.v1",
        target_representation_id: "virea.canonical211.v3",
        target_skeleton_id: "vrm1.humanoid52.v1",
        resource_profile_id: "component-split",
        memory_strategy: "cuda_component_split",
        device: "cuda:0",
      },
    },
    vrma: {
      locator: "results/result-1/actor-0.vrma",
      byte_length: 4096,
      identity: { actor_id: "actor-0" },
    },
    vrmaHttpGet: vrmaNetworkObservation(),
    browser: {},
    avatarPath: "D:/virea-data/avatar.vrm",
    avatarUsageBasis: "local QA only",
    playback: {},
    consoleObservation: { errors: [], warnings: [], page_errors: [], request_failures: [] },
    screenshots: [],
  });

  assert.equal(observation.producer.client_self_report_accepted, false);
  assert.equal(observation.generation_mode, "fresh_web_job");
  assert.equal(Object.hasOwn(observation, "promotion"), false);
  assert.equal(observation.result.frame_count, 129);
});
