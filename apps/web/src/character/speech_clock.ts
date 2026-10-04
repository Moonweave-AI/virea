import type { Expression } from "./contracts";

export interface SpeechAnchor { event: "immediate" | "reply_start" | "reply_end" | "utterance_start" | "utterance_end"; utterance: number | null }
export interface SpeechObservation {
  epoch: number | null; active: boolean; available: boolean; remaining_seconds: number;
  text: string; packet_id: string | null; stream_id: string | null;
  clock_seconds: number; marks: Record<string, number>;
}

export function anchorKey(anchor: SpeechAnchor): string {
  const [channel, edge] = anchor.event.split("_");
  return anchor.utterance == null ? anchor.event.replace("_", ":") : `${channel}:${anchor.utterance}:${edge}`;
}

export function cueReached(anchor: SpeechAnchor, epoch: number | undefined, speech: SpeechObservation): boolean {
  if (anchor.event === "immediate") return true;
  const at = speech.marks[anchorKey(anchor)];
  return speech.epoch === epoch && at !== undefined && at <= speech.clock_seconds;
}

/** PCM markers become facts only as the audible clock crosses them. */
export class SpeechClock {
  private epoch: number | null = null;
  private marks = new Map<string, number>();
  private packet: Expression | null = null;
  private start = 0;
  private end = 0;

  reset(): void { this.epoch = null; this.marks.clear(); this.packet = null; this.start = this.end = 0; }

  begin(packet: Expression, start: number, duration: number): void {
    if (this.epoch !== packet.epoch) this.reset();
    this.epoch = packet.epoch; this.packet = packet; this.start = start; this.end = start + duration;
    for (const mark of packet.speech_marks ?? []) this.marks.set(mark.name, start + mark.offset_seconds);
  }

  observe(now: number, motionReady: boolean): SpeechObservation {
    const active = Boolean(this.packet) && now >= this.start && now < this.end;
    return { epoch: this.epoch, active, available: active && motionReady, clock_seconds: now,
      remaining_seconds: Math.max(0, this.end - Math.max(now, this.start)),
      text: this.packet?.caption ?? this.packet?.text ?? "", packet_id: this.packet?.id ?? null,
      stream_id: this.packet?.stream_id ?? null, marks: Object.fromEntries([...this.marks].filter(([, at]) => at <= now)) };
  }
}
