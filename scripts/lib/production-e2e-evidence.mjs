import { basename, isAbsolute, relative, resolve } from "node:path";
import { createConnection, createServer } from "node:net";
import { performance } from "node:perf_hooks";

export const BROWSER_OBSERVATION_SCHEMA = "virea.production_browser_observation.v1.0.0";
export const VIEWER_TELEMETRY_SCHEMA = "virea.viewer_telemetry.v1.0.0";
export const MANAGED_API_LIFECYCLE_SCHEMA = "virea.managed_api_lifecycle.v1.0.0";
const MANAGED_API_GRACEFUL_SHUTDOWN_MS = 45_000;
const MANAGED_API_FORCE_SHUTDOWN_MS = 5_000;
const VIREA_HOME_TOKEN = "${VIREA_HOME}";
const LOCAL_PATH_DETAIL_REDACTED = "local path detail redacted";
const WINDOWS_LOCAL_PATH = /(?:^|[\s"'=:(/])(?:[a-z]:[\\/]|\\\\)/i;
const POSIX_LOCAL_PATH = /(?:^|[\s"'=:(])\/(?!\/|api(?:\/|$)|app(?:\/|$)|docs(?:\/|$)|openapi\.json(?:\s|$))[A-Za-z0-9._-]+(?:\/|$)/;


function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}


export function portableHomeText(value, home) {
  if (typeof value !== "string" || typeof home !== "string" || !home.trim()) return value;
  const rawHome = home.replace(/[\\/]+$/, "");
  const variants = new Set([
    rawHome,
    rawHome.replaceAll("\\", "/"),
    rawHome.replaceAll("/", "\\"),
  ]);
  let portable = value;
  for (const variant of [...variants].sort((left, right) => right.length - left.length)) {
    const flags = /^[a-z]:/i.test(variant) ? "gi" : "g";
    portable = portable.replace(new RegExp(escapeRegularExpression(variant), flags), VIREA_HOME_TOKEN);
  }
  return portable.includes(VIREA_HOME_TOKEN) ? portable.replaceAll("\\", "/") : portable;
}


function replaceKnownLocalPath(value, path, token) {
  if (typeof value !== "string" || typeof path !== "string" || !path.trim()) return value;
  const rawPath = path.replace(/[\\/]+$/, "");
  const variants = new Set([
    rawPath,
    rawPath.replaceAll("\\", "/"),
    rawPath.replaceAll("/", "\\"),
  ]);
  let portable = value;
  for (const variant of [...variants].sort((left, right) => right.length - left.length)) {
    const flags = /^[a-z]:/i.test(variant) ? "gi" : "g";
    portable = portable.replace(new RegExp(escapeRegularExpression(variant), flags), token);
  }
  return portable.includes(token) ? portable.replaceAll("\\", "/") : portable;
}


export function portableHomePayload(value, home) {
  if (Array.isArray(value)) return value.map((item) => portableHomePayload(item, home));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, portableHomePayload(item, home)]),
    );
  }
  return typeof value === "string" ? portableHomeText(value, home) : value;
}


export function assertPortablePayload(value, label = "payload") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertPortablePayload(item, `${label}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => assertPortablePayload(item, `${label}.${key}`));
    return;
  }
  if (typeof value === "string" && (WINDOWS_LOCAL_PATH.test(value) || POSIX_LOCAL_PATH.test(value))) {
    throw new Error(`${label} contains a non-portable local absolute path`);
  }
}


export function portableDiagnosticPayload(
  value,
  { home, knownPaths = [] } = {},
) {
  if (Array.isArray(value)) {
    return value.map((item) => portableDiagnosticPayload(item, { home, knownPaths }));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        portableDiagnosticPayload(item, { home, knownPaths }),
      ]),
    );
  }
  if (typeof value !== "string") return value;
  let portable = portableHomeText(value, home);
  for (const replacement of knownPaths) {
    portable = replaceKnownLocalPath(portable, replacement?.path, replacement?.token);
  }
  if (WINDOWS_LOCAL_PATH.test(portable) || POSIX_LOCAL_PATH.test(portable)) {
    return LOCAL_PATH_DETAIL_REDACTED;
  }
  return portable;
}


function requirePositiveDuration(value, label) {
  const duration = Number(value);
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`${label} must be a positive finite duration`);
  }
  return duration;
}


export async function fetchJsonWithTimeout(
  url,
  {
    timeoutMs = 30_000,
    fetchImpl = globalThis.fetch,
    label = "API request",
  } = {},
) {
  const boundedTimeoutMs = requirePositiveDuration(timeoutMs, `${label} timeout`);
  if (typeof fetchImpl !== "function") throw new Error(`${label} fetch implementation is unavailable`);
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, Math.max(1, Math.ceil(boundedTimeoutMs)));
  try {
    const response = await fetchImpl(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`${label} failed: HTTP ${response.status}`);
    return await response.json();
  } catch (error) {
    if (timedOut || controller.signal.aborted) {
      throw new Error(
        `${label} timed out after ${Math.max(1, Math.ceil(boundedTimeoutMs))} ms`,
        { cause: error },
      );
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}


export async function waitForApiHealth(
  baseUrl,
  {
    timeoutMs = 60_000,
    attemptTimeoutMs = 2_000,
    pollMs = 250,
    fetchImpl = globalThis.fetch,
    monotonicNow = () => performance.now(),
    sleep = (delayMs) => new Promise((resolveWait) => setTimeout(resolveWait, delayMs)),
  } = {},
) {
  const totalTimeoutMs = requirePositiveDuration(timeoutMs, "API readiness timeout");
  const perAttemptTimeoutMs = requirePositiveDuration(
    attemptTimeoutMs,
    "API readiness attempt timeout",
  );
  const pollDelayMs = Number(pollMs);
  if (!Number.isFinite(pollDelayMs) || pollDelayMs < 0) {
    throw new Error("API readiness poll interval must be finite and non-negative");
  }
  const healthUrl = new URL("/api/v1/health", baseUrl);
  const started = monotonicNow();
  const deadline = started + totalTimeoutMs;
  let lastFailure = "health probe was not attempted";
  while (true) {
    const remainingMs = deadline - monotonicNow();
    if (remainingMs <= 0) break;
    const boundedAttemptMs = Math.min(perAttemptTimeoutMs, remainingMs);
    try {
      const health = await fetchJsonWithTimeout(healthUrl, {
        timeoutMs: boundedAttemptMs,
        fetchImpl,
        label: "control-plane health probe",
      });
      if (
        health?.schema_version !== "virea.health.v1.0.0"
        || health?.status !== "ready"
        || health?.control_plane_ready !== true
        || !/^\d+\.\d+\.\d+$/.test(String(health?.version || ""))
      ) {
        throw new Error("control-plane health response does not satisfy the readiness contract");
      }
      return health;
    } catch (error) {
      lastFailure = String(error?.message || error);
    }
    const afterAttemptRemainingMs = deadline - monotonicNow();
    if (afterAttemptRemainingMs <= 0) break;
    await sleep(Math.min(pollDelayMs, afterAttemptRemainingMs));
  }
  const elapsedMs = monotonicNow() - started;
  throw new Error(
    `control plane did not become ready within ${Math.ceil(totalTimeoutMs)} ms `
    + `(elapsed ${Math.ceil(elapsedMs)} ms): ${lastFailure}`,
  );
}


function waitForChildExit(child, timeoutMs) {
  if (child.exitCode != null || child.signalCode != null) return Promise.resolve(true);
  return new Promise((resolveWait) => {
    let settled = false;
    let timer = null;
    const onExit = () => finish(true);
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (timer != null) clearTimeout(timer);
      child.off("exit", onExit);
      resolveWait(value);
    };
    child.once("exit", onExit);
    timer = setTimeout(() => finish(false), timeoutMs);
  });
}


export async function stopManagedApi(
  child,
  {
    gracefulTimeoutMs = MANAGED_API_GRACEFUL_SHUTDOWN_MS,
    forceTimeoutMs = MANAGED_API_FORCE_SHUTDOWN_MS,
  } = {},
) {
  if (child.exitCode != null || child.signalCode != null) {
    return {
      stdin_eof_requested: false,
      graceful: false,
      forced: false,
      exit_code: child.exitCode,
      exit_signal: child.signalCode,
    };
  }
  let stdinEofRequested = false;
  if (child.stdin && !child.stdin.destroyed) {
    try {
      child.stdin.end();
      stdinEofRequested = true;
    } catch {
      // A broken cooperative channel is recorded below and forces a non-promotable fallback.
    }
  }
  if (stdinEofRequested && await waitForChildExit(child, gracefulTimeoutMs)) {
    return {
      stdin_eof_requested: true,
      graceful: child.exitCode === 0 && child.signalCode == null,
      forced: false,
      exit_code: child.exitCode,
      exit_signal: child.signalCode,
    };
  }
  let forced = false;
  try {
    forced = child.kill("SIGTERM") || forced;
  } catch {
    // Continue to the final kill attempt and preserve the observed exit state.
  }
  if (!(await waitForChildExit(child, forceTimeoutMs))) {
    try {
      forced = child.kill("SIGKILL") || forced;
    } catch {
      // The caller records the unresolved exit state and rejects promotion.
    }
    await waitForChildExit(child, forceTimeoutMs);
  }
  return {
    stdin_eof_requested: stdinEofRequested,
    graceful: false,
    forced,
    exit_code: child.exitCode,
    exit_signal: child.signalCode,
  };
}


function loopbackPortState(host, port) {
  return new Promise((resolveProbe) => {
    const socket = createConnection({ host, port });
    let settled = false;
    const finish = (state) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolveProbe(state);
    };
    socket.setTimeout(500, () => finish("unknown"));
    socket.once("connect", () => finish("open"));
    socket.once("error", (error) => finish(error?.code === "ECONNREFUSED" ? "closed" : "unknown"));
  });
}


function exclusiveLoopbackBindState(host, port) {
  return new Promise((resolveProbe) => {
    const server = createServer();
    let settled = false;
    const finish = (state) => {
      if (settled) return;
      settled = true;
      resolveProbe(state);
    };
    server.once("error", (error) => {
      finish(error?.code === "EADDRINUSE" ? "in_use" : "unknown");
    });
    server.listen({ host, port, exclusive: true }, () => {
      const address = server.address();
      const exactHost = typeof address === "object"
        && address != null
        && address.address === host
        && address.port === port;
      server.close((error) => finish(!error && exactHost ? "available" : "unknown"));
    });
  });
}


export async function waitForLoopbackPortClosed(
  {
    host,
    port,
    timeoutMs = 5_000,
    pollMs = 50,
    probe = loopbackPortState,
    bindProbe = exclusiveLoopbackBindState,
  },
) {
  const normalizedHost = String(host).replace(/^\[|\]$/g, "");
  if (!["127.0.0.1", "localhost", "::1"].includes(normalizedHost)) {
    throw new Error("managed API lifecycle probes only a loopback listener");
  }
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new Error("managed API lifecycle port is invalid");
  }
  const deadline = Date.now() + timeoutMs;
  while (true) {
    const state = await probe(normalizedHost, port);
    if (state === "closed") return "connection_refused";
    if (state === "unknown") {
      const bindState = await bindProbe(normalizedHost, port);
      if (bindState === "available") return "exclusive_bind_available";
    }
    if (Date.now() >= deadline) return null;
    await new Promise((resolveWait) => setTimeout(resolveWait, pollMs));
  }
}


export function buildManagedApiLifecycle({
  managed,
  processSpawned,
  startedAt,
  stoppedAt,
  pid,
  loopbackPort,
  shutdown,
  portCloseMethod,
}) {
  const validPortCloseMethod = [
    "connection_refused",
    "exclusive_bind_available",
  ].includes(portCloseMethod) ? portCloseMethod : null;
  return {
    schema_version: MANAGED_API_LIFECYCLE_SCHEMA,
    managed: Boolean(managed),
    process_spawned: processSpawned === true,
    started_at: startedAt,
    stopped_at: stoppedAt,
    pid: Number.isSafeInteger(pid) && pid > 0 ? pid : null,
    loopback_port: Number.isSafeInteger(loopbackPort) ? loopbackPort : null,
    stdin_eof_requested: shutdown?.stdin_eof_requested === true,
    graceful: shutdown?.graceful === true,
    forced: shutdown?.forced === true,
    exit_code: Number.isSafeInteger(shutdown?.exit_code) ? shutdown.exit_code : null,
    exit_signal: typeof shutdown?.exit_signal === "string" ? shutdown.exit_signal : null,
    port_closed: validPortCloseMethod != null,
    port_close_method: validPortCloseMethod,
  };
}

export function acceptanceDefaults(manifest) {
  const acceptance = manifest?.production_acceptance;
  const request = acceptance?.request;
  if (!request || request.model_id !== manifest?.model?.id) {
    throw new Error(`model ${manifest?.model?.id || "<unknown>"} has no matching production acceptance`);
  }
  const prompt = request.input?.prompt;
  const fps = request.parameters?.fps;
  const seed = request.parameters?.seed;
  if (typeof prompt !== "string" || !prompt.trim()) throw new Error("production prompt is empty");
  if (!Number.isFinite(fps) || fps <= 0) throw new Error("production fps is not positive");
  if (!Number.isSafeInteger(seed) || seed < 0) throw new Error("production seed is invalid");
  let seconds = request.parameters?.seconds;
  if (seconds == null && Number.isFinite(request.input?.motion_length_frames)) {
    seconds = request.input.motion_length_frames / fps;
  }
  if (seconds == null && Number.isFinite(request.parameters?.motion_length_frames)) {
    seconds = request.parameters.motion_length_frames / fps;
  }
  if (seconds == null && Number.isFinite(request.parameters?.num_frames)) {
    seconds = request.parameters.num_frames / fps;
  }
  if (!Number.isFinite(seconds) || seconds <= 0) throw new Error("production duration is unavailable");
  return { prompt: prompt.trim(), fps, seed, seconds, request: structuredClone(request) };
}

export function assertExternalPath(candidate, checkoutRoot, label) {
  const resolved = resolve(candidate);
  const checkout = resolve(checkoutRoot);
  const fromCheckout = relative(checkout, resolved);
  if (fromCheckout === "" || (!fromCheckout.startsWith("..") && !isAbsolute(fromCheckout))) {
    throw new Error(`${label} must be outside the source checkout: ${resolved}`);
  }
  return resolved;
}

export function evidenceLocator(candidate) {
  const normalized = String(candidate).replaceAll("\\", "/");
  const parts = normalized.split("/");
  if (
    !normalized
    || normalized.startsWith("/")
    || parts[0].includes(":")
    || parts.some((part) => !part || part === "." || part === "..")
  ) {
    throw new Error(`evidence locator must be a clean relative path: ${candidate}`);
  }
  return normalized;
}

export function screenshotRecord(kind, path, outputDir, byteLength) {
  const locator = evidenceLocator(relative(outputDir, path));
  if (!Number.isSafeInteger(byteLength) || byteLength <= 0) {
    throw new Error(`${kind} screenshot is empty`);
  }
  return { kind, locator, byte_length: byteLength };
}

export function resultArtifactUrlPath(resultId, locator) {
  const normalizedLocator = evidenceLocator(locator);
  const artifactName = normalizedLocator.split("/").at(-1);
  if (typeof resultId !== "string" || !resultId) throw new Error("result identity is empty");
  if (!artifactName) throw new Error("result artifact locator has no basename");
  return `/api/v1/results/${encodeURIComponent(resultId)}/artifacts/${encodeURIComponent(artifactName)}`;
}

export function isVrmaArtifactUrl(candidate) {
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    return false;
  }
  const parts = parsed.pathname.split("/");
  if (
    parts.length !== 7
    || parts[1] !== "api"
    || parts[2] !== "v1"
    || parts[3] !== "results"
    || parts[5] !== "artifacts"
  ) {
    return false;
  }
  try {
    return decodeURIComponent(parts[4]).length > 0
      && decodeURIComponent(parts[6]).toLowerCase().endsWith(".vrma");
  } catch {
    return false;
  }
}

export function isApplicationJavascriptUrl(candidate) {
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    return false;
  }
  return /^\/app\/assets\/index-[A-Za-z0-9_-]+\.js$/.test(parsed.pathname)
    && !parsed.search
    && !parsed.hash;
}

function normalizedNetworkUrl(candidate, label) {
  try {
    return new URL(candidate).href;
  } catch (error) {
    throw new Error(`${label} URL is invalid: ${candidate}`, { cause: error });
  }
}

export function applicationJavascriptHttpGetObservation({ requests, responses }) {
  const javascriptRequests = requests.filter((record) => isApplicationJavascriptUrl(record.url));
  const javascriptResponses = responses.filter((record) => isApplicationJavascriptUrl(record.url));
  if (javascriptRequests.length !== 1) {
    throw new Error(
      `expected exactly one hashed application JavaScript request, observed ${javascriptRequests.length}`,
    );
  }
  if (javascriptResponses.length !== 1) {
    throw new Error(
      `expected exactly one hashed application JavaScript response, observed ${javascriptResponses.length}`,
    );
  }
  const request = javascriptRequests[0];
  const response = javascriptResponses[0];
  if (
    normalizedNetworkUrl(request.url, "application JavaScript request")
    !== normalizedNetworkUrl(response.url, "application JavaScript response")
  ) {
    throw new Error("application JavaScript request and response URLs differ");
  }
  if (request.method !== "GET" || response.method !== "GET") {
    throw new Error("application JavaScript must be requested and returned through GET");
  }
  if (response.status !== 200) {
    throw new Error(`application JavaScript response was HTTP ${response.status}`);
  }
  if (!Number.isSafeInteger(response.bodyByteLength) || response.bodyByteLength <= 0) {
    throw new Error("application JavaScript response body is empty or too large");
  }
  if (response.contentLength != null && response.contentLength !== response.bodyByteLength) {
    throw new Error("application JavaScript Content-Length differs from response body");
  }
  return {
    url_path: new URL(request.url).pathname,
    method: "GET",
    status: 200,
    body_byte_length: response.bodyByteLength,
    content_length: response.contentLength,
    unique_request_count: javascriptRequests.length,
    unique_response_count: javascriptResponses.length,
  };
}

export function vrmaHttpGetObservation({
  baseUrl,
  resultId,
  locator,
  byteLength,
  requests,
  responses,
}) {
  if (!Number.isSafeInteger(byteLength) || byteLength <= 0) {
    throw new Error("VRMA immutable artifact byte length is invalid");
  }
  const urlPath = resultArtifactUrlPath(resultId, locator);
  const expectedUrl = new URL(urlPath, baseUrl).href;
  const vrmaRequests = requests.filter((record) => isVrmaArtifactUrl(record.url));
  const vrmaResponses = responses.filter((record) => isVrmaArtifactUrl(record.url));
  if (vrmaRequests.length !== 1) {
    throw new Error(`expected exactly one VRMA artifact request, observed ${vrmaRequests.length}`);
  }
  if (vrmaResponses.length !== 1) {
    throw new Error(`expected exactly one VRMA artifact response, observed ${vrmaResponses.length}`);
  }
  const request = vrmaRequests[0];
  const response = vrmaResponses[0];
  if (normalizedNetworkUrl(request.url, "VRMA request") !== expectedUrl) {
    throw new Error("VRMA request URL differs from the current result artifact URL");
  }
  if (normalizedNetworkUrl(response.url, "VRMA response") !== expectedUrl) {
    throw new Error("VRMA response URL differs from the current result artifact URL");
  }
  if (request.method !== "GET" || response.method !== "GET") {
    throw new Error("VRMA artifact must be requested and returned through GET");
  }
  if (response.status !== 200) throw new Error(`VRMA artifact response was HTTP ${response.status}`);
  if (response.bodyByteLength !== byteLength) {
    throw new Error("VRMA response body length differs from the immutable artifact byte length");
  }
  if (response.contentLength != null && response.contentLength !== byteLength) {
    throw new Error("VRMA response Content-Length differs from the immutable artifact byte length");
  }
  return {
    url_path: urlPath,
    method: "GET",
    status: 200,
    body_byte_length: response.bodyByteLength,
    content_length: response.contentLength,
    unique_request_count: vrmaRequests.length,
    unique_response_count: vrmaResponses.length,
  };
}

export function resultBinding(modelResult, result, vrma, vrmaHttpGet) {
  const identity = result?.identity;
  if (!identity) throw new Error("VrmMotionResult has no immutable result identity");
  if (!vrma?.identity?.actor_id) throw new Error("VRMA export has no actor identity");
  if (!Number.isSafeInteger(vrma.byte_length) || vrma.byte_length <= 0) {
    throw new Error("VRMA export has no positive byte length");
  }
  return {
    result_id: result.result_id,
    job_id: result.job_id,
    model_id: identity.model_id,
    model_version: identity.model_version,
    runtime_variant_id: identity.runtime_variant_id,
    checkpoint_revision: identity.checkpoint_revision,
    native_representation_id: identity.native_representation_id,
    native_skeleton_id: identity.native_skeleton_id,
    target_representation_id: identity.target_representation_id,
    target_skeleton_id: identity.target_skeleton_id,
    resource_profile_id: identity.resource_profile_id,
    memory_strategy: identity.memory_strategy,
    device: identity.device,
    frame_count: modelResult.native.frame_count,
    vrma: {
      actor_id: vrma.identity.actor_id,
      locator: evidenceLocator(vrma.locator),
      byte_length: vrma.byte_length,
      http_get: structuredClone(vrmaHttpGet),
    },
  };
}

export function projectedBounds(raw) {
  const value = typeof raw === "string" ? JSON.parse(raw) : raw;
  const converted = {
    min_x: Number(value.minX),
    min_y: Number(value.minY),
    min_z: Number(value.minZ),
    max_x: Number(value.maxX),
    max_y: Number(value.maxY),
    max_z: Number(value.maxZ),
  };
  if (!Object.values(converted).every(Number.isFinite)) {
    throw new Error("Viewer did not expose finite projected avatar bounds");
  }
  return converted;
}

export function buildBrowserObservation({
  runId,
  startedAt,
  completedAt,
  generationMode,
  baseUrl,
  application,
  manifest,
  request,
  job,
  modelResult,
  result,
  vrma,
  vrmaHttpGet,
  browser,
  avatarPath,
  avatarUsageBasis,
  playback,
  consoleObservation,
  screenshots,
}) {
  const model = modelResult?.model;
  if (!model) throw new Error("ModelResult model binding is missing");
  if (!["fresh_web_job", "persisted_result_replay"].includes(generationMode)) {
    throw new Error("browser observation generation mode is invalid");
  }
  return {
    schema_version: BROWSER_OBSERVATION_SCHEMA,
    kind: "production_browser_observation",
    run_id: runId,
    started_at: startedAt,
    completed_at: completedAt,
    generation_mode: generationMode,
    producer: {
      id: "virea.production_browser_e2e_runner",
      version: "1.0.0",
      capture_mode: "out_of_process_browser_automation",
      client_self_report_accepted: false,
    },
    base_url: baseUrl,
    application: structuredClone(application),
    model: {
      id: model.id,
      plugin_version: model.plugin_version,
      upstream_revision: model.upstream_revision,
      runtime_id: model.runtime_id,
    },
    request,
    job: { id: job.id, state: job.state },
    result: resultBinding(modelResult, result, vrma, vrmaHttpGet),
    browser,
    avatar: {
      filename: basename(avatarPath),
      usage_basis: avatarUsageBasis,
      redistributed: false,
    },
    playback,
    console: consoleObservation,
    screenshots,
  };
}

export function parseCli(argv) {
  const options = {};
  const flags = new Set(["start-api", "headed"]);
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    if (flags.has(key)) {
      options[key] = true;
      continue;
    }
    const value = argv[index + 1];
    if (value == null || value.startsWith("--")) throw new Error(`missing value for --${key}`);
    options[key] = value;
    index += 1;
  }
  return options;
}
