import type { BodyProgram, BodyState } from "./contracts";
import type { BodyOwner } from "./body_authority";
import type { SpatialWindow } from "./spatial";
import type { SpeechAnchor, SpeechObservation } from "./speech_clock";

export interface BehaviorSlot {
  id: string; after: string | null; program_id: string | null; epoch: number;
  owner: BodyOwner; seconds: number; reason: string;
  activity_start: number; activity_end: number;
  speech_available: boolean;
  executor?: string | null; advances_activity?: boolean;
  speech_packet_id?: string | null;
  settling?: boolean; terminal?: boolean; handoff?: boolean;
  waiting_for?: SpeechAnchor | null;
  boundary_clock?: number | null;
  boundary_frame_seconds?: number | null;
}
type Prepared = { slot: BehaviorSlot; windows?: SpatialWindow[] };

/** A native boundary targets a specific audible instant, never a stale pose. */
export function boundaryExpired(slot: BehaviorSlot, clock: number): boolean {
  return slot.boundary_clock != null && clock + slot.seconds > slot.boundary_clock + (slot.boundary_frame_seconds ?? 0);
}

export function boundaryReady(slot: BehaviorSlot, clock: number): boolean {
  return slot.boundary_clock == null || clock >= slot.boundary_clock - slot.seconds;
}

/** A waiting lease must yield as soon as its task is replaced or released. */
export function reservationMatches(slot: BehaviorSlot, program: BodyProgram | null): boolean {
  const released = program?.finish_requested && !slot.settling &&
    (slot.advances_activity || !["completed", "failed", "interrupted"].includes(program.status));
  return slot.program_id === (program?.id ?? null) && !released;
}

interface BehaviorPort {
  state(): BodyState;
  speech(): SpeechObservation;
  hipHeight(): number;
  needed(): boolean;
  canStart(slot: BehaviorSlot): boolean;
  play(value: Prepared, current: () => boolean): Promise<void>;
  buffer?(value: Prepared): void;
  cancel?(): void;
  report(slot: BehaviorSlot): void;
}

class StaleReservation extends Error {}
const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

/** One executing reservation, at most one prepared successor. All waits share the audio clock. */
export class BehaviorPlayer {
  private controller: AbortController | null = null;
  running = false;
  owner: BodyOwner = "hold";

  private readonly port: BehaviorPort;
  constructor(port: BehaviorPort) { this.port = port; }
  stop(): void {
    if (this.controller) { this.controller.abort(); this.port.cancel?.(); }
    this.controller = null; this.running = false; this.owner = "hold";
  }

  async run(sessionId: string): Promise<void> {
    this.stop();
    const controller = this.controller = new AbortController();
    this.running = true;
    let feedbackError: unknown = null;
    let feedback: Promise<unknown> = Promise.resolve();
    const current = () => this.controller === controller && !controller.signal.aborted && !feedbackError;
    const request = async <T>(path: string, body: unknown): Promise<T> => {
      const response = await fetch(`/api/v1/characters/${encodeURIComponent(sessionId)}/behavior${path}`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(body), signal: controller.signal,
      });
      if (response.status === 409) throw new StaleReservation();
      if (!response.ok) throw new Error(`行为调度失败 (${response.status}): ${await response.text()}`);
      return response.json();
    };
    const plan = async (after: string | null): Promise<Prepared> => ({ slot: await request<BehaviorSlot>("/plan", {
      after, body: this.port.state(), speech: this.port.speech(),
    }) });
    const realize = async (value: Prepared): Promise<Prepared> => {
      if (value.slot.owner === "ardy" && !value.windows) {
        const result = await request<{ windows: SpatialWindow[]; slot?: BehaviorSlot }>(`/${value.slot.id}/motion`, {
          body: this.port.state(), hip_height: this.port.hipHeight(),
        });
        value.windows = result.windows;
        if (result.slot) value.slot = result.slot;
      }
      return value;
    };
    const receipt = (slot: BehaviorSlot, status: string) => {
      // Capture the observation NOW; sending may wait behind an earlier receipt.
      const body = structuredClone({ status, body: this.port.state(), clock_seconds: this.port.speech().clock_seconds });
      const sent = feedback.then(() => {
        if (feedbackError) throw feedbackError;
        return request(`/${slot.id}/feedback`, body);
      });
      feedback = sent.catch(error => {
        feedbackError = error;
        if (this.controller === controller && !controller.signal.aborted) this.port.cancel?.();
      });
      return sent;
    };
    let value: Prepared | null = null;
    let after: string | null = null;
    let active: BehaviorSlot | null = null;
    try {
      while (current() && (value || this.port.needed())) {
        let started: Promise<unknown>;
        try {
          // Planning depends on committed server state; rendering a ready successor does not.
          if (!value) { await feedback; if (feedbackError) throw feedbackError; }
          value = await realize(value ?? await plan(after));
          while (current() && (!this.port.canStart(value.slot)
            || !boundaryReady(value.slot, this.port.speech().clock_seconds))) await frame();
          if (!current()) break;
          const speech = this.port.speech();
          if (boundaryExpired(value.slot, speech.clock_seconds)) {
            await receipt(value.slot, "interrupted"); value = null; continue;
          }
          if (value.slot.owner !== "ardy" && (value.slot.speech_available !== speech.available
            || value.slot.owner === "sentiavatar" && value.slot.speech_packet_id && value.slot.speech_packet_id !== speech.packet_id)) {
            await receipt(value.slot, "interrupted"); value = null; continue;
          }
          started = receipt(value.slot, "playing");
          if (!after) await started;
          active = value.slot;
        } catch (error) {
          if (error instanceof StaleReservation && !feedbackError) { value = null; after = null; await frame(); continue; }
          throw error;
        }
        const executing = value;
        this.owner = executing.slot.owner;
        this.port.report(executing.slot);
        const playback = this.port.play(executing, current);
        // Preplan while the current model executes. Only a matching ARDY forecast is realized early.
        const upcoming = executing.slot.terminal || executing.slot.owner !== "ardy" ? Promise.resolve(null)
          : started.then(() => plan(executing.slot.id)).then(realize).then(next => {
            if (current()) this.port.buffer?.(next);
            return next;
          });
        const prepared = upcoming.then(v => ({ value: v, error: null }), error => ({ value: null, error }));
        await playback;
        if (!current()) break;
        void receipt(executing.slot, "completed");
        active = null;
        const next = await prepared;
        after = executing.slot.id;
        value = next.value;
        if (next.error && !(next.error instanceof StaleReservation)) throw next.error;
        if (!this.port.needed() && !value?.slot.settling && !value?.slot.handoff) {
          if (value) await receipt(value.slot, "interrupted").catch(() => {});
          value = null; break;
        }
      }
      await feedback;
      if (feedbackError) throw feedbackError;
    } catch (error) {
      if (active && current()) await receipt(active, "failed").catch(() => {});
      throw feedbackError ?? error;
    } finally {
      if (this.controller === controller) this.stop();
      controller.abort();
    }
  }
}
