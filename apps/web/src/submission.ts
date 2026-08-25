export interface PendingSubmissionAttempt {
  fingerprint: string;
  idempotencyKey: string;
  createdAt: string;
}

export interface SubmissionIdentity {
  vireaHome: string;
  modelId: string;
  task: string;
  prompt: string;
  seconds: number;
  seed: number;
  executionTarget: unknown;
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export async function submissionFingerprint(identity: SubmissionIdentity): Promise<string> {
  const canonicalIdentity = JSON.stringify(canonicalize({
    virea_home: identity.vireaHome,
    model_id: identity.modelId,
    task: identity.task,
    prompt: identity.prompt,
    seconds: identity.seconds,
    seed: identity.seed,
    execution_target: identity.executionTarget,
  }));
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonicalIdentity),
  );
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `sha256:${hex}`;
}

export function retainOrCreateSubmissionAttempt(
  current: PendingSubmissionAttempt | null,
  fingerprint: string,
  createKey: () => string,
  now: () => string,
): PendingSubmissionAttempt {
  if (current?.fingerprint === fingerprint) return current;
  return {
    fingerprint,
    idempotencyKey: createKey(),
    createdAt: now(),
  };
}

export function submissionAttemptWasPersisted(
  attempt: PendingSubmissionAttempt | null,
  jobs: ReadonlyArray<{ idempotency_key?: string | null }>,
): boolean {
  return Boolean(
    attempt
    && jobs.some((job) => job.idempotency_key === attempt.idempotencyKey),
  );
}
