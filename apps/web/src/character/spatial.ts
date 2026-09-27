import * as THREE from "three";
import type { VRM, VRMHumanBoneName } from "@pixiv/three-vrm";
import type { BodyState, Expression, SceneAction } from "./contracts";
import { RotationBridge } from "./continuity";
import { contactIK, contactRotation } from "./interaction";

export interface SpatialWindow {
  sequence: number; offset: number; seconds: number; fps: number;
  root: number[][]; rotations: Record<string, number[][]>;
  hip_height: number; continues: boolean; generation_seconds: number;
  total_seconds: number;
}

/** Native rolling model history is upstream; this class owns interpolation and body masks. */
export class SpatialPlayer {
  private abort: AbortController | null = null;
  private queue: SpatialWindow[] = [];
  private start = 0;
  private current: SpatialWindow | null = null;
  private bridges = new Map<string, RotationBridge>();
  private supportPose = new Map<string, THREE.Quaternion>();
  private supportPosition = new THREE.Vector3();
  private kind: SceneAction["kind"] = "stop";
  private holding = false;
  private floorStart = 0;
  private floorEnd = 0;
  private total = 0;
  private contact: THREE.Vector3 | null = null;
  contactError: number | null = null;
  contactState: Record<string, unknown> | null = null;
  active = false;
  underruns = 0;

  constructor(private readonly vrm: VRM, private readonly clock: () => number) {}

  stop(): void {
    this.abort?.abort(); this.abort = null; this.active = this.holding = false;
    this.queue = []; this.current = null; this.bridges.clear();
  }

  async run(packet: Expression, index: number, body: BodyState, hipHeight: number,
    onProgress: (elapsed: number, duration: number) => void = () => {}): Promise<void> {
    this.stop();
    const controller = this.abort = new AbortController();
    const action = packet.actions[index];
    if (!action || !packet.session_id) throw new Error("空间动作缺少所属会话");
    this.kind = action.kind;
    this.supportPosition.copy(this.vrm.humanoid.getNormalizedBoneNode("hips")!.position);
    this.supportPose.clear();
    for (const name of Object.keys(this.vrm.humanoid.humanBones)) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (bone) this.supportPose.set(name, bone.quaternion.clone());
    }
    this.contact = action.kind === "reach" && action.position
      ? new THREE.Vector3(action.position.x, action.position.y, action.position.z) : null;
    this.contactError = null;
    this.contactState = null;
    this.floorStart = this.vrm.scene.position.y;
    this.floorEnd = action.kind === "move_to" ? action.position!.y : this.floorStart;
    const response = await fetch(`/api/v1/characters/${encodeURIComponent(packet.session_id)}/spatial`, {
      method: "POST", headers: { "content-type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ packet_id: packet.id, epoch: packet.epoch, action_index: index, body, hip_height: hipHeight }),
    });
    if (!response.ok || !response.body) throw new Error(`空间动作服务失败 (${response.status})`);
    let ended = false, failure: unknown = null, sequence = 0;
    const read = async () => {
      const reader = response.body!.getReader(), decoder = new TextDecoder();
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
            this.total = item.total_seconds;
            this.queue.push(item);
            while (this.queue.length >= 12 && !controller.signal.aborted) await frame();
          }
          if (value.done) break;
        }
        if (!ended && !controller.signal.aborted) throw new Error("空间动作流提前中断");
      } catch (error) { failure = error; }
      finally { reader.releaseLock(); }
    };
    const reading = read();
    try {
      while (this.queue.length < 2 && !ended && !failure && !controller.signal.aborted) await frame();
      if (failure) throw failure;
      this.current = this.queue.shift() ?? null;
      this.start = this.clock(); this.underruns = 0;
      this.bridges.clear();
      if (this.current) for (const [name, values] of Object.entries(this.current.rotations)) {
        const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
        if (bone) this.bridges.set(name, new RotationBridge(bone.quaternion, this.quaternion(values[0]!), undefined, undefined, .35));
      }
      this.active = true;
      while (!controller.signal.aborted) {
        if (failure) throw failure;
        const elapsed = this.clock() - this.start;
        onProgress(Math.min(elapsed, this.total), this.total);
        if (this.current && elapsed >= this.current.offset + this.current.seconds) {
          if (this.queue.length) this.current = this.queue.shift()!;
          else if (ended) break;
          else this.underruns++;
        }
        await frame();
      }
      if (controller.signal.aborted) throw new DOMException("Interrupted", "AbortError");
      this.update(false);
      if (this.contact && (this.contactError ?? Infinity) > .05) throw new Error("未达到接触精度，请先移动到物体旁边。");
      this.holding = action.kind === "sit";
    } finally {
      controller.abort(); await reading;
      this.active = this.holding;
      this.abort = null;
    }
  }

  private quaternion(value: number[]): THREE.Quaternion {
    const q = new THREE.Quaternion().fromArray(value).normalize();
    if (this.vrm.meta.metaVersion === "0") { q.x *= -1; q.z *= -1; }
    return q;
  }

  update(speaking: boolean): void {
    const window = this.current;
    if (!this.active || !window) return;
    const elapsed = this.clock() - this.start;
    const cursor = THREE.MathUtils.clamp((elapsed - window.offset) * window.fps, 0, window.root.length - 1);
    const lo = Math.floor(cursor), hi = Math.min(lo + 1, window.root.length - 1), fraction = cursor - lo;
    for (const [name, values] of Object.entries(window.rotations)) {
      const bone = this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName);
      if (!bone) continue;
      const q = this.quaternion(values[lo]!).slerp(this.quaternion(values[hi]!), fraction);
      if (name === "chest" && !this.vrm.humanoid.getNormalizedBoneNode("upperChest")) {
        const extra = window.rotations.upperChest;
        if (extra) q.multiply(this.quaternion(extra[lo]!).slerp(this.quaternion(extra[hi]!), fraction));
      }
      // A nearby touch must not turn into a crouch or a step. Keep the executed
      // support pose; the model owns the arm chain and a small torso contribution.
      const support = this.supportPose.get(name);
      if (this.kind === "reach" && support) {
        q.copy(contactRotation(name, support, q));
      }
      // Locomotion owns hips/legs. Speech is a moderate upper-body layer;
      // reaching and sitting retain whole-body control, including balance.
      if (speaking && this.kind === "move_to" && /Arm|Hand|Shoulder|chest|Chest|neck|head/.test(name)) q.slerp(bone.quaternion, .3);
      this.bridges.get(name)?.apply(q, elapsed);
      bone.quaternion.copy(q);
    }
    const hips = this.vrm.humanoid.getNormalizedBoneNode("hips");
    if (hips && this.kind === "reach") hips.position.copy(this.supportPosition);
    if (hips && this.kind !== "reach") {
      const root = new THREE.Vector3().fromArray(window.root[lo]!).lerp(new THREE.Vector3().fromArray(window.root[hi]!), fraction);
      this.vrm.scene.updateMatrixWorld(true);
      const actual = hips.getWorldPosition(new THREE.Vector3());
      this.vrm.scene.position.x += root.x - actual.x;
      this.vrm.scene.position.z += root.z - actual.z;
      // Ground is an explicit destination constraint, separate from pelvis bob.
      this.vrm.scene.position.y = THREE.MathUtils.lerp(this.floorStart, this.floorEnd,
        THREE.MathUtils.smootherstep(elapsed, 0, Math.max(.4, this.total - 1)));
      this.vrm.scene.updateMatrixWorld(true);
      hips.position.copy(hips.parent!.worldToLocal(root));
    }
    if (this.contact) {
      const chain = ["rightLowerArm", "rightUpperArm"].map(name => this.vrm.humanoid.getNormalizedBoneNode(name as VRMHumanBoneName))
        .filter((node): node is THREE.Object3D => node !== null);
      const hand = this.vrm.humanoid.getNormalizedBoneNode("rightHand");
      if (hand) {
        this.contactError = contactIK(chain, hand, this.contact, THREE.MathUtils.smootherstep(elapsed, this.total - 1.2, this.total - .2));
        this.contactState = { target: this.contact.toArray(), hand: hand.getWorldPosition(new THREE.Vector3()).toArray(),
          chain: chain.map(node => ({ name: node.name, parent: node.parent?.name, position: node.getWorldPosition(new THREE.Vector3()).toArray() })) };
      }
    }
  }
}

const frame = () => new Promise<void>(resolve => requestAnimationFrame(() => resolve()));

export function validateSpatialWindow(value: SpatialWindow): void {
  const validRows = (rows: number[][], width: number) => Array.isArray(rows)
    && rows.length === value.root.length && rows.every(row => row.length === width && row.every(Number.isFinite));
  if (!Array.isArray(value.root) || value.root.length !== 9 || !validRows(value.root, 3)
    || value.fps !== 20 || value.seconds !== .4 || !Number.isFinite(value.total_seconds)
    || !Object.values(value.rotations).every(rows => validRows(rows, 4))) throw new Error("空间动作数据无效");
}
