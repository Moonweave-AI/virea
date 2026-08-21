import test from "node:test";
import assert from "node:assert/strict";

import { request } from "../src/http.ts";


test("a lightweight health request is bounded and parses its response", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, method: init?.method ?? "GET", signal: init?.signal });
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        schema_version: "virea.health.v1.0.0",
        version: "0.4.0",
        status: "ready",
        control_plane_ready: true,
      }),
    };
  };
  try {
    assert.deepEqual(await request("/health", {}, { timeoutMs: 5_000 }), {
      schema_version: "virea.health.v1.0.0",
      version: "0.4.0",
      status: "ready",
      control_plane_ready: true,
    });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/v1/health");
    assert.equal(calls[0].method, "GET");
    assert.equal(calls[0].signal instanceof AbortSignal, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("system diagnostics abort at their explicit caller-selected timeout", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => {
      reject(init.signal.reason ?? new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
  try {
    await assert.rejects(
      request("/system", {}, { timeoutMs: 25 }),
      /GET \/api\/v1\/system timed out after 25 ms/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("request preserves a caller abort instead of misreporting it as its own timeout", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => {
      reject(init.signal.reason ?? new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
  const caller = new AbortController();
  try {
    const pending = request("/models", { signal: caller.signal }, { timeoutMs: 1_000 });
    caller.abort(new Error("caller cancelled request"));
    await assert.rejects(pending, /caller cancelled request/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
