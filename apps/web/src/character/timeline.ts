import type { Expression } from "./contracts";

/** Audio is scheduled ahead; HTTP acknowledgements never set the playback clock. */
export class ExpressionTimeline {
  private stream: string | null = null;
  private origin = 0;
  private nextSequence = 0;
  private entries = new Map<string, { packet: Expression; audio: AudioBuffer; source?: AudioBufferSourceNode; start?: number }>();
  underruns = 0;

  constructor(private readonly context: AudioContext, private readonly output: AudioNode) {}

  register(packet: Expression, audio: AudioBuffer | null): void {
    if (!packet.stream_id || !audio || this.entries.has(packet.id)) return;
    this.entries.set(packet.id, { packet, audio });
    if (packet.stream_id === this.stream) this.scheduleReady();
  }

  private scheduleReady(): void {
    // Decode requests may resolve out of order. Never start a successor until
    // its predecessor has a fixed start, including any late-arrival shift.
    while (true) {
      const next = [...this.entries].find(([, entry]) =>
        entry.packet.stream_id === this.stream && entry.packet.sequence === this.nextSequence);
      if (!next) return;
      this.schedule(next[0]);
      this.nextSequence++;
    }
  }

  private schedule(id: string): void {
    const entry = this.entries.get(id)!;
    if (entry.source) return;
    let start = this.origin + (entry.packet.offset_seconds ?? 0);
    if (start < this.context.currentTime + 0.01) {
      const shift = this.context.currentTime + 0.04 - start;
      this.origin += shift;
      start += shift;
      this.underruns++;
    }
    const source = this.context.createBufferSource();
    source.buffer = entry.audio;
    source.connect(this.output);
    source.start(start);
    entry.source = source;
    entry.start = start;
  }

  begin(packet: Expression, audio: AudioBuffer): { source: AudioBufferSourceNode; start: number } {
    this.register(packet, audio);
    if (this.stream !== packet.stream_id) {
      this.stream = packet.stream_id!;
      this.origin = this.context.currentTime + 0.12 - (packet.offset_seconds ?? 0);
      this.nextSequence = packet.sequence ?? 0;
      this.scheduleReady();
    }
    const entry = this.entries.get(packet.id)!;
    return { source: entry.source!, start: entry.start! };
  }

  complete(id: string): void { this.entries.delete(id); }

  stop(): void {
    for (const entry of this.entries.values()) {
      entry.source?.stop();
      entry.source?.disconnect();
    }
    this.entries.clear();
    this.stream = null;
  }
}
