export interface RequestOptions {
  timeoutMs?: number;
}

export const FAST_API_TIMEOUT_MS = 30_000;

export async function request<T>(
  path: string,
  init: RequestInit = {},
  { timeoutMs = FAST_API_TIMEOUT_MS }: RequestOptions = {},
): Promise<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new Error("API request timeout must be a positive finite duration");
  }
  const { signal: callerSignal, ...requestInit } = init;
  const controller = new AbortController();
  let timedOut = false;
  const forwardCallerAbort = (): void => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) forwardCallerAbort();
  else callerSignal?.addEventListener("abort", forwardCallerAbort, { once: true });
  const timer = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, Math.ceil(timeoutMs));
  const method = requestInit.method ?? "GET";
  const label = `${method} /api/v1${path}`;
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...requestInit,
      // VIREA state can change in another CLI process. Browser HTTP caches
      // must never turn a successful reconciliation request into stale UI.
      cache: "no-store",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(requestInit.body ? { "Content-Type": "application/json" } : {}),
        ...requestInit.headers,
      },
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(`${label} failed: ${response.status} ${response.statusText}: ${detail}`);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (timedOut) throw new Error(`${label} timed out after ${Math.ceil(timeoutMs)} ms`, { cause: error });
    throw error;
  } finally {
    globalThis.clearTimeout(timer);
    callerSignal?.removeEventListener("abort", forwardCallerAbort);
  }
}
