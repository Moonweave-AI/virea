import type { BodyState } from "./contracts";
import type { BodyOwner } from "./body_authority";
import type { SpatialWindow } from "./spatial";

export interface BehaviorSlot {
  id: string; after: string | null; program_id: string | null; epoch: number;
  owner: BodyOwner; seconds: number; reason: string;
  activity_start: number; activity_end: number;
  speech_available: boolean;
  settling?: boolean; terminal?: boolean;
}
type Prepared = { slot: BehaviorSlot; windows?: SpatialWindow[] };
interface BehaviorPort {
  state(): BodyState;
  speech(): { available: boolean; text: string; remaining_seconds: number };
  hipHeight(): number;
  needed(): boolean;
  canStart(slot: BehaviorSlot): boolean;
  play(value: Prepared, current: () => boolean): Promise<void>;
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
  stop(): void { this.controller?.abort(); this.controller = null; this.running = false; this.owner = "hold"; }

  async run(sessionId: string): Promise<void> {
    this.stop();
    const controller = this.controller = new AbortController();
    this.running = true;
    const current = () => this.controller === controller && !controller.signal.aborted;
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
    const receipt = (slot: BehaviorSlot, status: string) => request(`/${slot.id}/feedback`, { status, body: this.port.state() });
    let value: Prepared | null = null;
    let after: string | null = null;
    let active: BehaviorSlot | null = null;
    try {
      while (current() && (value || this.port.needed())) {
        try {
          value = await realize(value ?? await plan(after));
          while (current() && !this.port.canStart(value.slot)) await frame();
          if (!current()) break;
          if (value.slot.owner !== "ardy" && value.slot.speech_available !== this.port.speech().available) {
            await receipt(value.slot, "interrupted"); value = null; continue;
          }
          await receipt(value.slot, "playing");
          active = value.slot;
        } catch (error) {
          if (error instanceof StaleReservation) { value = null; after = null; await frame(); continue; }
          throw error;
        }
        const executing = value;
        this.owner = executing.slot.owner;
        this.port.report(executing.slot);
        const playback = this.port.play(executing, current);
        // Preplan while the current model executes. Only a matching ARDY forecast is realized early.
        const upcoming = executing.slot.terminal ? Promise.resolve(null)
          : plan(executing.slot.id).then(v => executing.slot.owner === "ardy" ? realize(v) : v);
        const prepared = upcoming.then(v => ({ value: v, error: null }), error => ({ value: null, error }));
        await playback;
        const next = await prepared;
        if (!current()) break;
        await receipt(executing.slot, "completed");
        active = null;
        after = executing.slot.id;
        value = next.value;
        if (next.error && !(next.error instanceof StaleReservation)) throw next.error;
        if (!this.port.needed()) {
          if (value) await receipt(value.slot, "interrupted").catch(() => {});
          value = null; break;
        }
      }
    } catch (error) {
      if (active && current()) await receipt(active, "failed").catch(() => {});
      throw error;
    } finally {
      if (current()) this.stop();
      controller.abort();
    }
  }
}
