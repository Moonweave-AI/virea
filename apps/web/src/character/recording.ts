import * as THREE from "three";
import type { BodyState, Expression, FaceTrack } from "./contracts";
import type { SpatialWindow } from "./spatial";

type Frame = { at: number; body: BodyState; face: Record<string, number>; owner: string };
export interface SpeechCue { id: string; at: number; seconds: number; text: string; url: string; sequence?: number }

/** Records what was actually presented, in the output audio clock's coordinates. */
export class PerformanceRecording {
  private origin: number | null = null;
  private frames: Frame[] = [];
  readonly speech: SpeechCue[] = [];
  private audio = new Map<string, AudioBuffer>();
  readonly drivers: { at: number; owner: string; reason: string; id: string }[] = [];
  private finished = false;

  begin(clock: number): void { this.origin ??= clock; }
  get duration(): number { return Math.max(this.frames.at(-1)?.at ?? 0, ...this.speech.map(c => c.at + c.seconds)); }
  get ready(): boolean { return this.frames.length > 1; }
  get audioSeconds(): number { return this.speech.reduce((sum, c) => sum + c.seconds, 0); }
  get capturing(): boolean { return this.origin !== null && !this.finished; }
  elapsed(clock: number): number { return this.origin === null ? 0 : Math.max(0, clock - this.origin); }
  finish(): void { this.finished = true; }

  addSpeech(packet: Expression, clock: number, seconds: number, buffer?: AudioBuffer): void {
    if (!packet.audio_url || this.speech.some(c => c.id === packet.id)) return;
    this.begin(clock);
    this.speech.push({ id: packet.id, at: this.elapsed(clock), seconds,
      text: packet.caption ?? packet.text, url: packet.audio_url, sequence: packet.sequence });
    if (buffer) this.audio.set(packet.id, buffer);
  }
  audioCues(): { at: number; buffer: AudioBuffer }[] {
    return this.speech.map(c => {
      const buffer = this.audio.get(c.id);
      if (!buffer) throw new Error("这段录制的本地音频已不可用");
      return { at: c.at, buffer };
    });
  }
  driver(clock: number, owner: string, reason: string, id: string): void {
    this.begin(clock); this.drivers.push({ at: this.elapsed(clock), owner, reason, id });
  }
  observe(clock: number, body: BodyState, face: Record<string, number>, owner: string): void {
    if (!this.capturing) return;
    const { history, ...pose } = body;
    const at = this.elapsed(clock);
    if (this.frames.length && at <= this.frames.at(-1)!.at) return;
    this.frames.push({ at, body: pose, face, owner });
  }

  sample(seconds: number): Frame {
    let lo = 0, hi = this.frames.length - 1;
    while (lo < hi) { const mid = Math.ceil((lo + hi) / 2); if (this.frames[mid]!.at <= seconds) lo = mid; else hi = mid - 1; }
    const a = this.frames[lo]!, b = this.frames[Math.min(lo + 1, this.frames.length - 1)]!;
    const t = a === b ? 0 : THREE.MathUtils.clamp((seconds - a.at) / (b.at - a.at), 0, 1);
    const pose = Object.fromEntries(Object.entries(a.body.pose).map(([name, q]) => [name,
      new THREE.Quaternion().fromArray(q).slerp(new THREE.Quaternion().fromArray(b.body.pose[name] ?? q), t).toArray(),
    ])) as BodyState["pose"];
    const lerp = (x: number, y: number) => THREE.MathUtils.lerp(x, y, t);
    return { at: seconds, owner: a.owner, body: { ...a.body, pose,
      position: { x: lerp(a.body.position.x, b.body.position.x), y: lerp(a.body.position.y, b.body.position.y), z: lerp(a.body.position.z, b.body.position.z) },
      pelvis_height: lerp(a.body.pelvis_height ?? 1, b.body.pelvis_height ?? 1),
    }, face: Object.fromEntries(Object.entries(a.face).map(([name, v]) => [name, lerp(v, b.face[name] ?? v)])) };
  }

  assets(hipHeight: number, fps = 20): { windows: SpatialWindow[]; face: FaceTrack } {
    if (!this.ready) throw new Error("尚无完整播放录制");
    const duration = Math.ceil(this.duration * fps) / fps;
    const samples = Array.from({ length: Math.round(duration * fps) + 1 }, (_, i) => this.sample(i / fps));
    const names = Object.keys(samples[0]!.face);
    return { windows: [{ sequence: 0, offset: 0, seconds: duration, total_seconds: duration, fps,
      hip_height: hipHeight, continues: false, generation_seconds: 0, phase_label: "完整表达回放",
      root: samples.map(s => [s.body.position.x, s.body.position.y + (s.body.pelvis_height ?? hipHeight), s.body.position.z]),
      rotations: Object.fromEntries(Object.keys(samples[0]!.body.pose).map(name => [name, samples.map(s => s.body.pose[name]!)])),
    }], face: { fps, names, values: samples.map(s => names.map(name => s.face[name] ?? 0)) } };
  }

  summary() { return { duration_seconds: this.duration, frames: this.frames.length, audio_seconds: this.audioSeconds,
    speech: this.speech, drivers: this.drivers, complete: this.finished }; }
}

/** Keep the recorded offsets and silent gaps; never pair a whole motion with its last utterance. */
export function mixRecordedAudio(context: Pick<AudioContext, "sampleRate" | "createBuffer">,
  duration: number, cues: { at: number; buffer: AudioBuffer }[]): AudioBuffer {
  const result = context.createBuffer(1, Math.ceil(duration * context.sampleRate), context.sampleRate);
  const output = result.getChannelData(0);
  for (const cue of cues) {
    const input = cue.buffer.getChannelData(0), start = Math.round(cue.at * context.sampleRate);
    for (let i = 0; i < Math.ceil(cue.buffer.duration * context.sampleRate) && start + i < output.length; i++) {
      const position = i * cue.buffer.sampleRate / context.sampleRate, lower = Math.floor(position);
      output[start + i]! += THREE.MathUtils.lerp(input[lower] ?? 0, input[Math.min(lower + 1, input.length - 1)] ?? 0, position - lower);
    }
  }
  return result;
}
