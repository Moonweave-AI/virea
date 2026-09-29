import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { BodyState, Expression, SceneAction } from "./contracts";
import { RotationBridge } from "./continuity";
import { contactIK } from "./interaction";
import { samplePosition, sampleRotation } from "./motion_sampling";
import { GroundSupport } from "./support";

export interface SpatialWindow {
  sequence: number; offset: number; seconds: number; fps: number;
  root: number[][]; rotations: Record<string, number[][]>;
  joints?: Record<string, number[][]>;
  hip_height: number; continues: boolean; generation_seconds: number;
  total_seconds: number; history_frames?: number;
  phase_index?: number; phase_label?: string; phase_kind?: SceneAction["kind"];
  phase_seconds?: number; phase_offset?: number; prompt?: string;
  target?: { x: number; y: number; z: number } | null;
}

/** A single rolling program owns the whole body, across every prompt transition. */
export class SpatialPlayer {
  private abort: AbortController | null = null;
  private queue: SpatialWindow[] = [];
  private start = 0;
  private current: SpatialWindow | null = null;
  private previous: SpatialWindow | null = null;
  private bridges = new Map<string, RotationBridge>();
  private recording: { id: string; windows: SpatialWindow[] } | null = null;
  private holding = false;
  private stalledAt: number | null = null;
  private floor = 0;
  private total = 0;
  private phaseContactError = Infinity;
  contactError: number | null = null;
  contactState: Record<string, unknown> | null = null;
  active = false;
  underruns = 0;
  phase = "";
  phaseIndex = 0;
  elapsed = 0;
  readonly joints = new Map<string, THREE.Vector3>();
  private readonly vrm: VRM;
  private readonly clock: () => number;
  private readonly support: GroundSupport;

  constructor(vrm: VRM, clock: () => number) { this.vrm = vrm; this.clock = clock; this.support = new GroundSupport(vrm); }

  stop(): void {
    this.abort?.abort(); this.abort = null; this.active = this.holding = false;
    this.queue = []; this.current = null; this.bridges.clear(); this.joints.clear();
  }

  export(): SpatialWindow[] { return this.recording?.windows ?? []; }

  async run(packet: Expression, body: BodyState, hipHeight: number,
    onProgress: (elapsed: number, duration: number) => void = () => {}): Promise<void> {
    this.stop();
    this.previous = null;
    const controller = this.abort = new AbortController();
    if (!packet.preview) this.recording = null;
    this.contactError = null; this.contactState = null; this.stalledAt = null;
    this.floor = this.vrm.scene.position.y;
    this.phaseContactError = Infinity;
    let ended = false, failure: unknown = null, sequence = 0;
    const captured: SpatialWindow[] = [];
    const read = async () => {
      if (packet.spatial_windows) {
        for (const window of packet.spatial_windows) validateSpatialWindow(window);
        this.queue = [...packet.spatial_windows]; captured.push(...this.queue); ended = true; return;
      }
      if (packet.preview) {
        if (this.recording?.id !== packet.id) throw new Error("本地尚无这段动作的录制");
        this.queue = [...this.recording.windows]; ended = true; return;
      }
      if (!packet.session_id) throw new Error("空间动作缺少所属会话");
      const index = packet.actions.findIndex(a => !["look_at", "stop"].includes(a.kind));
      const endpoint = packet.body_program_id ? `body/${encodeURIComponent(packet.body_program_id)}` : "spatial";
      const response = await fetch(`/api/v1/characters/${encodeURIComponent(packet.session_id)}/${endpoint}`, {
        method: "POST", headers: { "content-type": "application/json" }, signal: controller.signal,
        body: JSON.stringify(packet.body_program_id ? { body, hip_height: hipHeight }
          : { packet_id: packet.id, epoch: packet.epoch, action_index: index, full_program: true, body, hip_height: hipHeight }),
      });
      if (!response.ok || !response.body) throw new Error(`空间动作服务失败 (${response.status})`);
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let pending = "";
      try {
        while (!controller.signal.aborted) {
          const value = await reader.read();
          pending += decoder.decode(value.value, { stream: !value.done });
          let newline: number;
          while ((newline = pending.indexOf("\n")) >= 0) {
            const line = pending.slice(0, newline); pending = pending.slice(newline + 1);
            if (!line.trim()) continue;
            const item = JSON.parse(line);
            if (item.error) throw new Error(item.error);
            if (item.done) { ended = true; continue; }
            if (item.sequence !== sequence++) throw new Error("空间动作序列不连续");
            validateSpatialWindow(item);
            captured.push(item); this.queue.push(item);
            while (this.queue.length >= 12 && !controller.signal.aborted) await frame();
            if (controller.signal.aborted) return;
          }
          if (value.done) break;
        }
        if (!ended && !controller.signal.aborted) throw new Error("空间动作流提前中断");
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    };
    const reading = read().catch(error => { failure = error; });
    try {
      while (this.queue.reduce((seconds, window) => seconds + window.seconds, 0) < 1.6 && !ended && !failure && !controller.signal.aborted) await frame();
      if (failure) throw failure;
      if (controller.signal.aborted) throw new DOMException("Interrupted", "AbortError");
      this.current = this.queue.shift() ?? null;
      this.total = this.current?.total_seconds ?? 0;
      this.start = this.clock(); this.underruns = 0; this.elapsed = 0;
      if (this.current && !packet.temporal) for (const [name, values] of Object.entries(this.current.rotations)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (bone) this.bridges.set(name, new RotationBridge(bone.quaternion, this.quaternion(values[0]!), undefined, undefined, .35));
      }
      this.active = true;
      while (!controller.signal.aborted) {
        if (failure) throw failure;
        const now = this.clock();
        this.elapsed = (this.stalledAt ?? now) - this.start;
        if (this.current && this.elapsed >= this.current.offset + this.current.seconds) {
          if (this.queue.length) {
            if (this.queue[0]!.phase_index !== this.current.phase_index) {
              this.checkContact(); this.phaseContactError = Infinity;
            }
            if (this.stalledAt !== null) { this.start += now - this.stalledAt; this.stalledAt = null; }
            this.previous = this.current;
            this.current = this.queue.shift()!;
          } else if (ended) {
            if (!packet.temporal || (this.current.phase_offset ?? 0) + (this.current.phase_seconds ?? 0) <= this.total + 1e-5) this.checkContact();
            break;
          }
          else if (this.stalledAt === null) { this.stalledAt = now; this.underruns++; }
        }
        this.phase = this.current?.phase_label ?? "生成动作";
        this.phaseIndex = this.current?.phase_index ?? 0;
        onProgress(Math.min(this.elapsed, this.total), this.total);
        await frame();
      }
      if (controller.signal.aborted) throw new DOMException("Interrupted", "AbortError");
      this.elapsed = this.total; this.update(false);
      this.holding = packet.end_state === "hold";
      if (!packet.preview) this.recording = { id: packet.id, windows: captured };
    } finally {
      controller.abort(); await reading;
      if (this.abort === controller) { this.active = this.holding; this.abort = null; }
    }
  }

  private quaternion(value: number[]): THREE.Quaternion {
    const q = new THREE.Quaternion().fromArray(value).normalize();
    if (this.vrm.meta.metaVersion === "0") { q.x *= -1; q.z *= -1; }
    return q;
  }

  private checkContact(): void {
    if (this.current?.phase_kind === "reach" && this.phaseContactError > .08) {
      throw new Error(`尚未碰到目标（最近距离 ${Number.isFinite(this.phaseContactError) ? (this.phaseContactError * 100).toFixed(1) : "未知"} 厘米），请调整站位后重试。`);
    }
  }

  update(_speaking: boolean): void {
    const window = this.current;
    if (!this.active || !window) return;
    const elapsed = this.holding ? this.total : (this.stalledAt ?? this.clock()) - this.start;
    const cursor = THREE.MathUtils.clamp((elapsed - window.offset) * window.fps, 0, window.root.length - 1);
    const next = this.queue[0];
    for (const [name, values] of Object.entries(window.rotations)) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (!bone) continue;
      const q = sampleRotation(values, cursor, this.previous?.rotations[name], next?.rotations[name]);
      if (this.vrm.meta.metaVersion === "0") { q.x *= -1; q.z *= -1; }
      if (name === "chest" && !this.vrm.humanoid.getNormalizedBoneNode("upperChest")) {
        const extra = window.rotations.upperChest;
        if (extra) {
          const upper = sampleRotation(extra, cursor, this.previous?.rotations.upperChest, next?.rotations.upperChest);
          if (this.vrm.meta.metaVersion === "0") { upper.x *= -1; upper.z *= -1; }
          q.multiply(upper);
        }
      }
      this.bridges.get(name)?.apply(q, elapsed);
      bone.quaternion.copy(q);
    }
    const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
    if (hips) {
      const root = samplePosition(window.root, cursor, this.previous?.root, next?.root);
      this.vrm.scene.updateMatrixWorld(true);
      const actual = hips.getWorldPosition(new THREE.Vector3());
      this.vrm.scene.position.x += root.x - actual.x;
      this.vrm.scene.position.z += root.z - actual.z;
      this.vrm.scene.position.y = this.floor;
      this.vrm.scene.updateMatrixWorld(true);
      hips.position.copy(hips.parent!.worldToLocal(root));
    }
    this.joints.clear();
    for (const [name, rows] of Object.entries(window.joints ?? {})) {
      this.joints.set(name, samplePosition(rows, cursor, this.previous?.joints?.[name], next?.joints?.[name]));
    }
    this.support.align(this.joints);
    if (window.phase_kind === "reach" && window.target) {
      const target = new THREE.Vector3(window.target.x, window.target.y, window.target.z);
      const hand = this.vrm.humanoid.getNormalizedBoneNode("rightHand");
      if (hand) {
        const error = hand.getWorldPosition(new THREE.Vector3()).distanceTo(target);
        // Correct only a small avatar-proportion residual, never a distant goal.
        if (error < .18) {
          const chain = ["rightLowerArm", "rightUpperArm"].map(name => this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName))
            .filter((node): node is THREE.Object3D => node !== null);
          const end = (window.phase_offset ?? 0) + (window.phase_seconds ?? this.total);
          contactIK(chain, hand, target, THREE.MathUtils.smootherstep(elapsed, end - 1.2, end - .2));
        }
        const distance = hand.getWorldPosition(new THREE.Vector3()).distanceTo(target);
        this.phaseContactError = Math.min(this.phaseContactError, distance);
        this.contactError = this.phaseContactError;
        this.contactState = { target: target.toArray(), hand: hand.getWorldPosition(new THREE.Vector3()).toArray(), distance, closestDistance: this.phaseContactError };
      }
    }
  }
}

const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

export function validateSpatialWindow(value: SpatialWindow): void {
  const validRows = (rows: number[][], width: number) => Array.isArray(rows)
    && rows.length === value.root.length && rows.every(row => row.length === width && row.every(Number.isFinite));
  if (!Array.isArray(value.root) || value.root.length < 2 || !validRows(value.root, 3)
    || !(value.fps > 0) || !Number.isFinite(value.fps) || !(value.seconds > 0)
    || Math.abs((value.root.length - 1) / value.fps - value.seconds) > 1e-6 || !Number.isFinite(value.total_seconds)
    || !Number.isFinite(value.offset) || !value.rotations.hips
    || !Object.values(value.rotations).every(rows => validRows(rows, 4))) throw new Error("空间动作数据无效");
}
