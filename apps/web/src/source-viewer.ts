import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

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
const TELEMETRY_INTERVAL_MS = 250;

function disposeMaterial(material: THREE.Material | THREE.Material[]): void {
  if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
  else material.dispose();
}

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
  private readonly controls: OrbitControls;
  private readonly timer = new THREE.Timer();
  private readonly resizeObserver: ResizeObserver;
  private readonly grid = new THREE.GridHelper(10, 20, 0x416244, 0x1d2b22);
  private readonly root = new THREE.Vector3();
  private readonly rootAnchor = new THREE.Vector3();
  private readonly relativeCenter = new THREE.Vector3(0, 0.9, 0);
  /** Canonical target for root follow; OrbitControls.target may additionally include user pan. */
  private readonly framedTarget = new THREE.Vector3();
  private readonly followTarget = new THREE.Vector3();
  private readonly followTranslation = new THREE.Vector3();
  private actorRenders: ActorRender[] = [];
  private preview: SourceSkeletonPreview | null = null;
  private contentStatus: SourceViewerStatus = {
    kind: "idle",
    message: "生成完成后显示重定向前骨架",
  };
  private playheadSeconds = 0;
  private currentFrame = -1;
  private framingRadius = 1.2;
  private framingDistance = 3.2;
  private hasCameraFraming = false;
  private frameHandle: number | null = null;
  private lastTelemetryAt = Number.NEGATIVE_INFINITY;
  private active = true;
  private contextLost = false;
  private disposed = false;

  public constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly onStatus: (status: SourceViewerStatus) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene.background = new THREE.Color(0x0c1110);
    this.scene.add(this.grid);
    this.camera.position.set(2.2, 1.6, 3.2);
    this.camera.lookAt(0, 0.9, 0);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, 0.9, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enablePan = true;
    this.controls.enableRotate = true;
    this.controls.enableZoom = true;
    this.controls.screenSpacePanning = true;
    this.controls.update();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.canvas.dataset.sourceViewer = "virea.source_skeleton_viewer.v1.0.0";
    this.canvas.dataset.viewerState = "idle";
    this.canvas.dataset.sourceFrame = "0";
    this.canvas.dataset.cameraControls = "orbit-rotate-zoom-pan-double-click-reset";
    this.canvas.dataset.webglContextLost = "false";
    this.canvas.dataset.webglContextRecovery = "ready";
    this.canvas.dataset.renderLoop = "stopped";
    this.canvas.addEventListener("dblclick", this.handleResetGesture);
    this.canvas.addEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.addEventListener("webglcontextrestored", this.markWebglContextRestored);
    document.addEventListener("visibilitychange", this.handleVisibilityChange);
    this.timer.connect(document);
    this.resize();
    this.syncRenderLoop();
  }

  public load(value: SourceSkeletonPreview): void {
    const preview = validateSourceSkeletonPreview(value);
    this.clearActors();
    this.preview = preview;
    this.playheadSeconds = 0;
    this.currentFrame = -1;
    this.canvas.dataset.sourceFrame = "0";
    this.hasCameraFraming = false;
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
    this.updateFrame(0, true);
    this.publishStatus({
      kind: "playing",
      message: `正在播放模型原生骨架 · ${preview.skeleton_id}`,
      duration: preview.duration_seconds,
    });
  }

  public replay(): void {
    if (!this.preview) throw new Error("还没有可播放的重定向前骨架");
    this.playheadSeconds = 0;
    this.updateFrame(0);
    this.currentFrame = 0;
    this.canvas.dataset.sourceFrame = "0";
  }

  public clear(message = "生成完成后显示重定向前骨架"): void {
    this.preview = null;
    this.playheadSeconds = 0;
    this.currentFrame = -1;
    this.hasCameraFraming = false;
    this.clearActors();
    this.canvas.dataset.sourceFrame = "0";
    this.resetView();
    this.publishStatus({ kind: "idle", message });
  }

  public setActive(active: boolean): void {
    if (this.disposed) return;
    this.active = active;
    this.controls.enabled = active && !this.contextLost;
    if (active) this.resize();
    this.syncRenderLoop();
  }

  /** Restore authored framing around the skeleton's current root position. */
  public resetView(): void {
    if (this.disposed) return;
    if (this.hasCameraFraming) {
      this.updateCameraFraming(false);
      this.controls.target.copy(this.followTarget);
      this.camera.position.set(
        this.followTarget.x + this.framingDistance * 0.65,
        this.followTarget.y + this.framingDistance * 0.2,
        this.followTarget.z + this.framingDistance,
      );
    } else {
      this.controls.target.set(0, 0.9, 0);
      this.camera.position.set(2.2, 1.6, 3.2);
    }
    this.camera.lookAt(this.controls.target);
    this.controls.update();
    const resetCount = Number(this.canvas.dataset.cameraResetCount ?? "0") + 1;
    this.canvas.dataset.cameraResetCount = String(resetCount);
  }

  public dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.active = false;
    this.stopRenderLoop();
    this.timer.dispose();
    this.resizeObserver.disconnect();
    this.clearActors();
    this.controls.dispose();
    this.grid.geometry.dispose();
    disposeMaterial(this.grid.material);
    this.renderer.renderLists.dispose();
    this.renderer.dispose();
    this.canvas.removeEventListener("dblclick", this.handleResetGesture);
    this.canvas.removeEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.removeEventListener("webglcontextrestored", this.markWebglContextRestored);
    document.removeEventListener("visibilitychange", this.handleVisibilityChange);
  }

  private clearActors(): void {
    for (const actor of this.actorRenders) {
      this.scene.remove(actor.lines, actor.points);
      actor.lines.geometry.dispose();
      actor.points.geometry.dispose();
      disposeMaterial(actor.lines.material);
      disposeMaterial(actor.points.material);
    }
    this.actorRenders = [];
  }

  private computeFraming(): void {
    if (!this.preview) return;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let minZ = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let maxZ = Number.NEGATIVE_INFINITY;
    for (const actor of this.preview.actors) {
      const jointCount = actor.joint_names.length;
      for (let frame = 0; frame < this.preview.frame_count; frame += 1) {
        const frameOffset = frame * jointCount * 3;
        const rootX = actor.positions_xyz[frameOffset] ?? 0;
        const rootY = actor.positions_xyz[frameOffset + 1] ?? 0;
        const rootZ = actor.positions_xyz[frameOffset + 2] ?? 0;
        for (let joint = 0; joint < jointCount; joint += 1) {
          const offset = frameOffset + joint * 3;
          const x = (actor.positions_xyz[offset] ?? 0) - rootX;
          const y = (actor.positions_xyz[offset + 1] ?? 0) - rootY;
          const z = (actor.positions_xyz[offset + 2] ?? 0) - rootZ;
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          minZ = Math.min(minZ, z);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
          maxZ = Math.max(maxZ, z);
        }
      }
    }
    const sizeX = maxX - minX;
    const sizeY = maxY - minY;
    const sizeZ = maxZ - minZ;
    this.relativeCenter.set((minX + maxX) / 2, (minY + maxY) / 2, (minZ + maxZ) / 2);
    this.framingRadius = Math.max(sizeX, sizeY, sizeZ, 0.5) * 0.75;
  }

  private updateFrame(frame: number, initializeCamera = false): void {
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
      if (initializeCamera || !this.hasCameraFraming) {
        this.rootAnchor.copy(this.root);
        this.framedTarget.copy(this.root).add(this.relativeCenter);
        this.followTarget.copy(this.framedTarget);
        this.hasCameraFraming = true;
        this.updateCameraFraming(true);
      } else {
        const desiredX = this.framedTarget.x + this.root.x - this.rootAnchor.x;
        const desiredZ = this.framedTarget.z + this.root.z - this.rootAnchor.z;
        this.followTranslation.set(
          desiredX - this.followTarget.x,
          0,
          desiredZ - this.followTarget.z,
        );
        this.followTarget.add(this.followTranslation);
        // Preserve the user's orbit, zoom, and pan by applying only the root delta.
        this.camera.position.add(this.followTranslation);
        this.controls.target.add(this.followTranslation);
      }
    }
    this.currentFrame = frame;
  }

  private updateCameraFraming(resetCamera: boolean): void {
    if (!this.hasCameraFraming) return;
    const aspect = Math.max(this.canvas.clientWidth, 1) / Math.max(this.canvas.clientHeight, 1);
    const verticalDistance = this.framingRadius / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.framingDistance = Math.max(verticalDistance, verticalDistance / Math.max(aspect, 0.55)) * 1.25;
    this.camera.near = Math.max(0.01, this.framingDistance / 100);
    this.camera.far = Math.max(100, this.framingDistance * 20);
    this.controls.minDistance = Math.max(this.framingDistance * 0.12, 0.05);
    this.controls.maxDistance = Math.max(this.framingDistance * 12, this.controls.minDistance + 1);
    this.camera.updateProjectionMatrix();
    if (resetCamera) this.resetView();
  }

  private resize(): void {
    if (this.disposed) return;
    const width = Math.max(this.canvas.clientWidth, 1);
    const height = Math.max(this.canvas.clientHeight, 1);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    if (this.hasCameraFraming) this.updateCameraFraming(false);
    else this.camera.updateProjectionMatrix();
  }

  private publishStatus(status: SourceViewerStatus): void {
    this.contentStatus = status;
    if (!this.contextLost) this.emitStatus(status);
  }

  private emitStatus(status: SourceViewerStatus): void {
    this.canvas.dataset.viewerState = status.kind;
    this.canvas.dataset.viewerMessage = status.message;
    if (status.duration == null) delete this.canvas.dataset.viewerDurationSeconds;
    else this.canvas.dataset.viewerDurationSeconds = String(status.duration);
    this.onStatus(status);
  }

  private handleResetGesture = (): void => {
    this.resetView();
  };

  private handleVisibilityChange = (): void => {
    this.syncRenderLoop();
  };

  private markWebglContextLost = (event: Event): void => {
    event.preventDefault();
    if (this.disposed || this.contextLost) return;
    this.contextLost = true;
    this.canvas.dataset.webglContextLost = "true";
    this.canvas.dataset.webglContextRecovery = "lost";
    this.controls.enabled = false;
    this.syncRenderLoop();
    this.emitStatus({ kind: "error", message: "WebGL 上下文已丢失；正在等待浏览器恢复源骨架预览" });
  };

  private markWebglContextRestored = (): void => {
    if (this.disposed) return;
    this.contextLost = false;
    this.canvas.dataset.webglContextLost = "false";
    this.canvas.dataset.webglContextRecovery = "restored";
    this.canvas.dataset.webglContextRestoredAt = new Date().toISOString();
    this.renderer.resetState();
    this.controls.enabled = this.active;
    this.resize();
    this.emitStatus(this.contentStatus);
    this.syncRenderLoop();
  };

  private updateTelemetry(timestamp: DOMHighResTimeStamp, frame: number): void {
    if (timestamp - this.lastTelemetryAt < TELEMETRY_INTERVAL_MS) return;
    this.lastTelemetryAt = timestamp;
    this.canvas.dataset.sourceFrame = String(frame);
    this.canvas.dataset.renderCalls = String(this.renderer.info.render.calls);
    this.canvas.dataset.renderTriangles = String(this.renderer.info.render.triangles);
    this.canvas.dataset.renderGeometries = String(this.renderer.info.memory.geometries);
    this.canvas.dataset.renderTextures = String(this.renderer.info.memory.textures);
  }

  private shouldRender(): boolean {
    return !this.disposed && this.active && !this.contextLost && !document.hidden;
  }

  private syncRenderLoop(): void {
    if (this.shouldRender()) this.startRenderLoop();
    else this.stopRenderLoop();
  }

  private startRenderLoop(): void {
    if (this.frameHandle != null || !this.shouldRender()) return;
    this.timer.reset();
    this.canvas.dataset.renderLoop = "running";
    this.frameHandle = requestAnimationFrame(this.tick);
  }

  private stopRenderLoop(): void {
    if (this.frameHandle != null) cancelAnimationFrame(this.frameHandle);
    this.frameHandle = null;
    this.canvas.dataset.renderLoop = "stopped";
  }

  private tick = (timestamp: DOMHighResTimeStamp): void => {
    this.frameHandle = null;
    if (!this.shouldRender()) {
      this.syncRenderLoop();
      return;
    }
    this.timer.update(timestamp);
    const measuredDelta = this.timer.getDelta();
    // A RAF timestamp can precede a Timer.reset() performed later in the same
    // browser frame. Never let that small negative delta produce frame -1 and
    // write undefined joint values into GPU buffers.
    const delta = Number.isFinite(measuredDelta)
      ? Math.max(0, Math.min(measuredDelta, 0.1))
      : 0;
    let frame = Number(this.canvas.dataset.sourceFrame ?? "0");
    if (this.preview) {
      this.playheadSeconds += delta;
      frame = Math.floor(this.playheadSeconds * this.preview.fps) % this.preview.frame_count;
      if (frame !== this.currentFrame) this.updateFrame(frame);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.updateTelemetry(timestamp, frame);
    if (this.shouldRender()) this.frameHandle = requestAnimationFrame(this.tick);
  };
}
