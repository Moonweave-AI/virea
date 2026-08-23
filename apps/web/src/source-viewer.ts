import * as THREE from "three";

import type { SourceSkeletonActor, SourceSkeletonPreview } from "./contracts";

export interface SourceViewerStatus {
  kind: "idle" | "loading" | "playing" | "error";
  message: string;
  duration?: number;
}

type ActorRender = {
  source: SourceSkeletonActor;
  lines: THREE.LineSegments;
  points: THREE.Points;
  linePositions: Float32Array;
  pointPositions: Float32Array;
};

const ACTOR_COLORS = [0x9dff43, 0x69a7ff, 0xffb34f, 0xff70a6];

export function validateSourceSkeletonPreview(
  preview: SourceSkeletonPreview,
): SourceSkeletonPreview {
  if (preview.schema_version !== "virea.source_skeleton_preview.v1.0.0") {
    throw new Error("源骨架预览契约版本不受支持");
  }
  if (preview.stage !== "model_output_pre_retarget") {
    throw new Error("源骨架预览不是重定向前产物");
  }
  if (!Number.isInteger(preview.frame_count) || preview.frame_count < 1) {
    throw new Error("源骨架帧数无效");
  }
  if (!Number.isFinite(preview.fps) || preview.fps <= 0) {
    throw new Error("源骨架 FPS 无效");
  }
  if (!preview.actors.length) throw new Error("源骨架预览没有 Actor");
  if (preview.display_transform.vrm_retarget_applied !== false) {
    throw new Error("源骨架预览错误地包含了 VRM 重定向");
  }
  for (const actor of preview.actors) {
    const jointCount = actor.joint_names.length;
    if (!actor.actor_id || jointCount < 1) throw new Error("源骨架 Actor 无效");
    if (actor.positions_xyz.length !== preview.frame_count * jointCount * 3) {
      throw new Error("源骨架位置数量与帧数、关节数不一致");
    }
    if (!actor.positions_xyz.every(Number.isFinite)) {
      throw new Error("源骨架包含 NaN 或 Infinity");
    }
    for (const [parent, child] of actor.edges) {
      if (
        !Number.isInteger(parent)
        || !Number.isInteger(child)
        || parent < 0
        || child < 0
        || parent >= jointCount
        || child >= jointCount
        || parent === child
      ) {
        throw new Error("源骨架包含无效连接");
      }
    }
  }
  return preview;
}

export class SourceSkeletonViewer {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(32, 1, 0.01, 500);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly timer = new THREE.Timer();
  private readonly resizeObserver: ResizeObserver;
  private readonly target = new THREE.Vector3();
  private readonly root = new THREE.Vector3();
  private readonly relativeCenter = new THREE.Vector3(0, 0.9, 0);
  private actorRenders: ActorRender[] = [];
  private preview: SourceSkeletonPreview | null = null;
  private playheadSeconds = 0;
  private framingRadius = 1.2;
  private frameHandle = 0;
  private active = true;
  private disposed = false;

  public constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly onStatus: (status: SourceViewerStatus) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene.background = new THREE.Color(0x0c1110);
    this.scene.add(new THREE.GridHelper(10, 20, 0x416244, 0x1d2b22));
    this.camera.position.set(2.2, 1.6, 3.2);
    this.camera.lookAt(0, 0.9, 0);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.canvas.dataset.sourceViewer = "virea.source_skeleton_viewer.v1.0.0";
    this.canvas.dataset.viewerState = "idle";
    this.canvas.dataset.sourceFrame = "0";
    this.timer.connect(document);
    this.resize();
    this.frameHandle = requestAnimationFrame(this.tick);
  }

  public load(value: SourceSkeletonPreview): void {
    const preview = validateSourceSkeletonPreview(value);
    this.clearActors();
    this.preview = preview;
    this.playheadSeconds = 0;
    this.actorRenders = preview.actors.map((actor, index) => {
      const color = ACTOR_COLORS[index % ACTOR_COLORS.length]!;
      const linePositions = new Float32Array(actor.edges.length * 2 * 3);
      const pointPositions = new Float32Array(actor.joint_names.length * 3);
      const lineGeometry = new THREE.BufferGeometry();
      lineGeometry.setAttribute("position", new THREE.BufferAttribute(linePositions, 3));
      const pointGeometry = new THREE.BufferGeometry();
      pointGeometry.setAttribute("position", new THREE.BufferAttribute(pointPositions, 3));
      const lines = new THREE.LineSegments(
        lineGeometry,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.92 }),
      );
      const points = new THREE.Points(
        pointGeometry,
        new THREE.PointsMaterial({ color: 0xffffff, size: 0.035, sizeAttenuation: true }),
      );
      this.scene.add(lines, points);
      return { source: actor, lines, points, linePositions, pointPositions };
    });
    this.computeFraming();
    this.updateFrame(0);
    this.canvas.dataset.viewerState = "playing";
    this.onStatus({
      kind: "playing",
      message: `正在播放模型原生骨架 · ${preview.skeleton_id}`,
      duration: preview.duration_seconds,
    });
  }

  public replay(): void {
    if (!this.preview) throw new Error("还没有可播放的重定向前骨架");
    this.playheadSeconds = 0;
    this.updateFrame(0);
  }

  public clear(message = "生成完成后显示重定向前骨架"): void {
    this.preview = null;
    this.playheadSeconds = 0;
    this.clearActors();
    this.canvas.dataset.viewerState = "idle";
    this.canvas.dataset.sourceFrame = "0";
    this.onStatus({ kind: "idle", message });
  }

  public setActive(active: boolean): void {
    if (this.disposed) return;
    this.active = active;
    if (active) this.resize();
  }

  public dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.active = false;
    cancelAnimationFrame(this.frameHandle);
    this.timer.dispose();
    this.resizeObserver.disconnect();
    this.clearActors();
    this.renderer.dispose();
  }

  private clearActors(): void {
    for (const actor of this.actorRenders) {
      this.scene.remove(actor.lines, actor.points);
      actor.lines.geometry.dispose();
      actor.points.geometry.dispose();
      (actor.lines.material as THREE.Material).dispose();
      (actor.points.material as THREE.Material).dispose();
    }
    this.actorRenders = [];
  }

  private computeFraming(): void {
    if (!this.preview) return;
    const minimum = new THREE.Vector3(Infinity, Infinity, Infinity);
    const maximum = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
    for (const actor of this.preview.actors) {
      const jointCount = actor.joint_names.length;
      for (let frame = 0; frame < this.preview.frame_count; frame += 1) {
        const frameOffset = frame * jointCount * 3;
        const rootX = actor.positions_xyz[frameOffset] ?? 0;
        const rootY = actor.positions_xyz[frameOffset + 1] ?? 0;
        const rootZ = actor.positions_xyz[frameOffset + 2] ?? 0;
        for (let joint = 0; joint < jointCount; joint += 1) {
          const offset = frameOffset + joint * 3;
          minimum.min(new THREE.Vector3(
            (actor.positions_xyz[offset] ?? 0) - rootX,
            (actor.positions_xyz[offset + 1] ?? 0) - rootY,
            (actor.positions_xyz[offset + 2] ?? 0) - rootZ,
          ));
          maximum.max(new THREE.Vector3(
            (actor.positions_xyz[offset] ?? 0) - rootX,
            (actor.positions_xyz[offset + 1] ?? 0) - rootY,
            (actor.positions_xyz[offset + 2] ?? 0) - rootZ,
          ));
        }
      }
    }
    const size = maximum.clone().sub(minimum);
    this.relativeCenter.copy(minimum).add(maximum).multiplyScalar(0.5);
    this.framingRadius = Math.max(size.x, size.y, size.z, 0.5) * 0.75;
  }

  private updateFrame(frame: number): void {
    if (!this.preview) return;
    this.actorRenders.forEach((render) => {
      const jointCount = render.source.joint_names.length;
      const frameOffset = frame * jointCount * 3;
      for (let joint = 0; joint < jointCount; joint += 1) {
        const sourceOffset = frameOffset + joint * 3;
        const targetOffset = joint * 3;
        render.pointPositions[targetOffset] = render.source.positions_xyz[sourceOffset]!;
        render.pointPositions[targetOffset + 1] = render.source.positions_xyz[sourceOffset + 1]!;
        render.pointPositions[targetOffset + 2] = render.source.positions_xyz[sourceOffset + 2]!;
      }
      render.source.edges.forEach(([parent, child], edgeIndex) => {
        const targetOffset = edgeIndex * 6;
        for (let axis = 0; axis < 3; axis += 1) {
          render.linePositions[targetOffset + axis] = render.pointPositions[parent * 3 + axis]!;
          render.linePositions[targetOffset + 3 + axis] = render.pointPositions[child * 3 + axis]!;
        }
      });
      (render.points.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
      (render.lines.geometry.getAttribute("position") as THREE.BufferAttribute).needsUpdate = true;
    });
    const primary = this.actorRenders[0];
    if (primary) {
      this.root.fromArray(primary.pointPositions, 0);
      this.target.copy(this.root).add(this.relativeCenter);
      const aspect = Math.max(this.canvas.clientWidth, 1) / Math.max(this.canvas.clientHeight, 1);
      const verticalDistance = this.framingRadius / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
      const distance = Math.max(verticalDistance, verticalDistance / Math.max(aspect, 0.55)) * 1.25;
      this.camera.position.set(
        this.target.x + distance * 0.65,
        this.target.y + distance * 0.2,
        this.target.z + distance,
      );
      this.camera.near = Math.max(0.01, distance / 100);
      this.camera.far = Math.max(100, distance * 20);
      this.camera.lookAt(this.target);
      this.camera.updateProjectionMatrix();
    }
    this.canvas.dataset.sourceFrame = String(frame);
  }

  private resize(): void {
    const width = Math.max(this.canvas.clientWidth, 1);
    const height = Math.max(this.canvas.clientHeight, 1);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  private tick = (timestamp: DOMHighResTimeStamp): void => {
    if (this.disposed) return;
    this.timer.update(timestamp);
    const delta = Math.min(this.timer.getDelta(), 0.1);
    if (this.active && this.preview) {
      this.playheadSeconds += delta;
      const frame = Math.floor(this.playheadSeconds * this.preview.fps) % this.preview.frame_count;
      this.updateFrame(frame);
    }
    if (this.active) this.renderer.render(this.scene, this.camera);
    this.frameHandle = requestAnimationFrame(this.tick);
  };
}
