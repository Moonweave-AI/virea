import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMHumanBoneName, VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import {
  VRMAnimationLoaderPlugin,
  createVRMAnimationClip,
  type VRMAnimation,
} from "@pixiv/three-vrm-animation";
import {
  assertFiniteClip,
  assertUsableAnimationRestHips,
  advancePlanarCameraFollow,
  computeCameraFraming,
  ensureVRMLookAtQuaternionProxy,
} from "./viewer-compat";

export interface ViewerStatus {
  kind: "idle" | "loading" | "ready" | "playing" | "error";
  message: string;
  duration?: number;
}

const TELEMETRY_INTERVAL_MS = 250;

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function disposeMaterial(material: THREE.Material | THREE.Material[]): void {
  if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
  else material.dispose();
}

export class RealVrmViewer {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly timer = new THREE.Timer();
  private readonly resizeObserver: ResizeObserver;
  private readonly grid = new THREE.GridHelper(10, 20, 0x34506a, 0x17202c);
  private vrm: VRM | null = null;
  private animation: VRMAnimation | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  private boundClip: THREE.AnimationClip | null = null;
  private readonly framedTarget = new THREE.Vector3();
  /** Canonical root-follow target, kept separate from the user's OrbitControls pan offset. */
  private readonly cameraTarget = new THREE.Vector3();
  private readonly hipsAnchor = new THREE.Vector3();
  private readonly hipsWorldPosition = new THREE.Vector3();
  private readonly followTranslation = new THREE.Vector3();
  private readonly avatarSize = new THREE.Vector3();
  private readonly avatarBoundsRelativeToHips = new THREE.Box3();
  private readonly projectedCorner = new THREE.Vector3();
  private readonly telemetryCorner = new THREE.Vector3();
  private hasCameraFraming = false;
  private framingDistance = 3.6;
  private snapCameraFollow = false;
  private frameHandle: number | null = null;
  private renderFrameCount = 0;
  private lastTelemetryAt = Number.NEGATIVE_INFINITY;
  private active = true;
  private contextLost = false;
  private disposed = false;
  private contentStatus: ViewerStatus = {
    kind: "idle",
    message: "载入 Avatar 后即可预览生成动作",
  };
  private avatarLoadEpoch = 0;
  private animationLoadEpoch = 0;
  private avatarLoadUrl: string | null = null;
  private animationLoadUrl: string | null = null;
  private avatarLoadPromise: Promise<void> | null = null;
  private animationLoadPromise: Promise<void> | null = null;
  private avatarObjectUrl: string | null = null;
  private animationObjectUrl: string | null = null;

  public constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly onStatus: (status: ViewerStatus) => void,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene.background = new THREE.Color(0x080b10);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x26334d, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(2, 4, 3);
    this.scene.add(key, this.grid);
    this.camera.position.set(0, 1.25, 3.6);
    this.camera.lookAt(0, 1, 0);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(0, 1, 0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.enablePan = true;
    this.controls.enableRotate = true;
    this.controls.enableZoom = true;
    this.controls.screenSpacePanning = true;
    this.controls.update();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.canvas.dataset.vireaViewerTelemetry = "virea.viewer_telemetry.v1.0.0";
    this.canvas.dataset.viewerState = "idle";
    this.canvas.dataset.cameraControls = "orbit-rotate-zoom-pan-double-click-reset";
    this.canvas.dataset.webglContextLost = "false";
    this.canvas.dataset.webglContextRecovery = "ready";
    this.canvas.dataset.renderLoop = "stopped";
    this.canvas.dataset.renderFrameCount = "0";
    this.canvas.dataset.mixerTimeSeconds = "0";
    this.canvas.dataset.avatarFullyVisible = "false";
    const context = this.renderer.getContext();
    const debugRenderer = context.getExtension("WEBGL_debug_renderer_info");
    this.canvas.dataset.webglContext = (
      typeof WebGL2RenderingContext !== "undefined" && context instanceof WebGL2RenderingContext
    ) ? "webgl2" : "webgl";
    this.canvas.dataset.webglVendor = String(
      context.getParameter(debugRenderer ? debugRenderer.UNMASKED_VENDOR_WEBGL : context.VENDOR),
    );
    this.canvas.dataset.webglRenderer = String(
      context.getParameter(debugRenderer ? debugRenderer.UNMASKED_RENDERER_WEBGL : context.RENDERER),
    );
    this.canvas.dataset.webglVersion = String(context.getParameter(context.VERSION));
    this.canvas.dataset.webglShadingLanguageVersion = String(
      context.getParameter(context.SHADING_LANGUAGE_VERSION),
    );
    this.canvas.addEventListener("dblclick", this.handleResetGesture);
    this.canvas.addEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.addEventListener("webglcontextrestored", this.markWebglContextRestored);
    document.addEventListener("visibilitychange", this.handleVisibilityChange);
    this.resize();
    this.timer.connect(document);
    this.syncRenderLoop();
  }

  public async loadAvatarFile(file: File): Promise<void> {
    if (!/\.(vrm|glb)$/i.test(file.name)) throw new Error("Avatar 必须是包含 VRM 扩展的 .vrm 或 .glb 文件");
    const objectUrl = URL.createObjectURL(file);
    if (this.avatarObjectUrl) URL.revokeObjectURL(this.avatarObjectUrl);
    this.avatarObjectUrl = objectUrl;
    try {
      await this.loadAvatar(objectUrl);
    } finally {
      if (this.avatarObjectUrl === objectUrl) {
        URL.revokeObjectURL(objectUrl);
        this.avatarObjectUrl = null;
      }
    }
  }

  public setActive(active: boolean): void {
    if (this.disposed) return;
    this.active = active;
    this.controls.enabled = active && !this.contextLost;
    if (active) this.resize();
    this.syncRenderLoop();
  }

  public async loadAnimationFile(file: File): Promise<void> {
    if (!/\.vrma$/i.test(file.name)) throw new Error("动作文件必须是 .vrma");
    const objectUrl = URL.createObjectURL(file);
    if (this.animationObjectUrl) URL.revokeObjectURL(this.animationObjectUrl);
    this.animationObjectUrl = objectUrl;
    try {
      await this.loadAnimation(objectUrl);
    } finally {
      if (this.animationObjectUrl === objectUrl) {
        URL.revokeObjectURL(objectUrl);
        this.animationObjectUrl = null;
      }
    }
  }

  public loadAnimation(url: string): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (url === this.animationLoadUrl && this.animationLoadPromise) return this.animationLoadPromise;

    const epoch = ++this.animationLoadEpoch;
    this.animationLoadUrl = url;
    this.publishStatus({ kind: "loading", message: "正在读取真实 VRMA…" });
    let pending: Promise<void>;
    pending = this.performAnimationLoad(url, epoch)
      .catch((error: unknown) => {
        if (this.disposed || epoch !== this.animationLoadEpoch) return;
        this.publishStatus({ kind: "error", message: `VRMA 读取失败：${describeError(error)}` });
        throw error;
      })
      .finally(() => {
        if (this.animationLoadPromise === pending) {
          this.animationLoadPromise = null;
          this.animationLoadUrl = null;
        }
      });
    this.animationLoadPromise = pending;
    return pending;
  }

  public play(): void {
    if (!this.vrm) throw new Error("请先加载 VRM Avatar");
    if (!this.animation) throw new Error("请先加载真实 VRMA 动作");
    this.bindAndPlay();
  }

  public clearAnimation(message = "载入 Avatar 后即可预览生成动作"): void {
    this.animationLoadEpoch += 1;
    this.animationLoadUrl = null;
    if (this.animationObjectUrl) {
      URL.revokeObjectURL(this.animationObjectUrl);
      this.animationObjectUrl = null;
    }
    this.disposeMixer();
    this.animation = null;
    this.canvas.dataset.mixerTimeSeconds = "0";
    this.publishStatus({
      kind: this.vrm ? "ready" : "idle",
      message: this.vrm ? "Avatar 已加载；请选择或载入 VRMA" : message,
    });
  }

  /** Restore the authored full-body framing around the Avatar's current root position. */
  public resetView(): void {
    if (this.disposed) return;
    if (this.hasCameraFraming) {
      this.updateCameraFraming(false);
      this.controls.target.copy(this.cameraTarget);
      this.camera.position.set(
        this.cameraTarget.x,
        this.cameraTarget.y,
        this.cameraTarget.z + this.framingDistance,
      );
    } else {
      this.controls.target.set(0, 1, 0);
      this.camera.position.set(0, 1.25, 3.6);
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
    this.avatarLoadEpoch += 1;
    this.animationLoadEpoch += 1;
    this.stopRenderLoop();
    this.timer.dispose();
    this.resizeObserver.disconnect();
    this.disposeMixer();
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
      this.vrm = null;
    }
    this.animation = null;
    this.controls.dispose();
    this.grid.geometry.dispose();
    disposeMaterial(this.grid.material);
    this.renderer.renderLists.dispose();
    this.renderer.dispose();
    this.canvas.removeEventListener("dblclick", this.handleResetGesture);
    this.canvas.removeEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.removeEventListener("webglcontextrestored", this.markWebglContextRestored);
    document.removeEventListener("visibilitychange", this.handleVisibilityChange);
    if (this.avatarObjectUrl) URL.revokeObjectURL(this.avatarObjectUrl);
    if (this.animationObjectUrl) URL.revokeObjectURL(this.animationObjectUrl);
    this.avatarObjectUrl = null;
    this.animationObjectUrl = null;
  }

  private loadAvatar(url: string): Promise<void> {
    if (this.disposed) return Promise.resolve();
    if (url === this.avatarLoadUrl && this.avatarLoadPromise) return this.avatarLoadPromise;

    const epoch = ++this.avatarLoadEpoch;
    this.avatarLoadUrl = url;
    this.publishStatus({ kind: "loading", message: "正在解析 VRM Avatar…" });
    let pending: Promise<void>;
    pending = this.performAvatarLoad(url, epoch)
      .catch((error: unknown) => {
        if (this.disposed || epoch !== this.avatarLoadEpoch) return;
        this.publishStatus({ kind: "error", message: `Avatar 读取失败：${describeError(error)}` });
        throw error;
      })
      .finally(() => {
        if (this.avatarLoadPromise === pending) {
          this.avatarLoadPromise = null;
          this.avatarLoadUrl = null;
        }
      });
    this.avatarLoadPromise = pending;
    return pending;
  }

  private async performAvatarLoad(url: string, epoch: number): Promise<void> {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (this.disposed || epoch !== this.avatarLoadEpoch) {
      VRMUtils.deepDispose(vrm?.scene ?? gltf.scene);
      return;
    }
    if (!vrm) {
      VRMUtils.deepDispose(gltf.scene);
      throw new Error("该 GLB 不含 VRM humanoid 扩展，不能应用 VRMA");
    }

    try {
      VRMUtils.removeUnnecessaryVertices(vrm.scene);
      VRMUtils.combineSkeletons(vrm.scene);
      VRMUtils.rotateVRM0(vrm);
      this.installAvatar(vrm);
    } catch (error) {
      if (this.vrm !== vrm) VRMUtils.deepDispose(vrm.scene);
      throw error;
    }

    if (this.animation) this.bindAndPlay();
    else this.publishStatus({ kind: "ready", message: "Avatar 已加载；请选择或载入 VRMA" });
  }

  private async performAnimationLoad(url: string, epoch: number): Promise<void> {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const animations = gltf.userData.vrmAnimations as VRMAnimation[] | undefined;
    if (this.disposed || epoch !== this.animationLoadEpoch) {
      VRMUtils.deepDispose(gltf.scene);
      return;
    }
    if (!animations?.length) {
      VRMUtils.deepDispose(gltf.scene);
      throw new Error("文件不含 VRMC_vrm_animation 数据");
    }

    this.disposeMixer();
    this.animation = animations[0] ?? null;
    this.bindAndPlay();
  }

  private installAvatar(vrm: VRM): void {
    vrm.scene.updateWorldMatrix(true, true);
    const box = new THREE.Box3().setFromObject(vrm.scene);
    if (box.isEmpty()) throw new Error("Avatar 没有可渲染的几何体");
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const hips = vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) throw new Error("Avatar 缺少 humanoid hips，无法建立根位移相机跟随");
    const hipsAnchor = hips.getWorldPosition(new THREE.Vector3());
    const aspect = Math.max(this.canvas.clientWidth, 1) / Math.max(this.canvas.clientHeight, 1);
    // Validate framing before releasing the currently usable Avatar.
    computeCameraFraming(
      size.x,
      size.y,
      size.z,
      aspect,
      THREE.MathUtils.degToRad(this.camera.fov),
    );

    this.disposeMixer();
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
    }
    this.vrm = vrm;
    this.scene.add(vrm.scene);
    this.avatarSize.copy(size);
    this.hipsAnchor.copy(hipsAnchor);
    this.avatarBoundsRelativeToHips.copy(box);
    this.avatarBoundsRelativeToHips.min.sub(this.hipsAnchor);
    this.avatarBoundsRelativeToHips.max.sub(this.hipsAnchor);
    this.framedTarget.copy(center);
    this.cameraTarget.copy(center);
    this.hasCameraFraming = true;
    this.updateCameraFraming(true);
  }

  private disposeMixer(): void {
    if (!this.mixer) {
      this.boundClip = null;
      return;
    }
    this.mixer.stopAllAction();
    if (this.boundClip) this.mixer.uncacheClip(this.boundClip);
    if (this.vrm) this.mixer.uncacheRoot(this.vrm.scene);
    this.mixer = null;
    this.boundClip = null;
  }

  private bindAndPlay(): void {
    if (!this.vrm || !this.animation) {
      this.publishStatus({ kind: "ready", message: "VRMA 已加载；载入 Avatar 后即可播放" });
      return;
    }
    assertUsableAnimationRestHips(this.animation);
    ensureVRMLookAtQuaternionProxy(this.vrm);
    const clip = createVRMAnimationClip(this.animation, this.vrm);
    if (clip.tracks.length === 0) throw new Error("VRMA 与该 Avatar 没有可播放的 humanoid track");
    assertFiniteClip(clip);

    this.disposeMixer();
    const mixer = new THREE.AnimationMixer(this.vrm.scene);
    mixer.addEventListener("loop", () => {
      // Root locomotion clips jump back to their first keyframe when looping.
      // Snap only on that discontinuity so the Avatar cannot outrun a camera
      // that is intentionally smooth during ordinary motion.
      this.snapCameraFollow = true;
    });
    mixer.clipAction(clip).reset().play();
    this.mixer = mixer;
    this.boundClip = clip;
    this.snapCameraFollow = true;
    this.publishStatus({ kind: "playing", message: "正在播放真实 VRMA", duration: clip.duration });
  }

  private updateCameraFraming(resetCamera: boolean): void {
    if (!this.hasCameraFraming) return;
    const aspect = Math.max(this.canvas.clientWidth, 1) / Math.max(this.canvas.clientHeight, 1);
    const framing = computeCameraFraming(
      this.avatarSize.x,
      this.avatarSize.y,
      this.avatarSize.z,
      aspect,
      THREE.MathUtils.degToRad(this.camera.fov),
    );
    this.framingDistance = framing.distance;
    this.camera.near = framing.near;
    this.camera.far = framing.far;
    this.controls.minDistance = Math.max(framing.distance * 0.12, 0.05);
    this.controls.maxDistance = Math.max(framing.distance * 12, this.controls.minDistance + 1);
    this.camera.updateProjectionMatrix();
    if (resetCamera) this.resetView();
  }

  private followAvatarHips(delta: number): void {
    if (!this.vrm || !this.hasCameraFraming) return;
    const hips = this.vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) return;
    hips.getWorldPosition(this.hipsWorldPosition);
    const previousTargetX = this.cameraTarget.x;
    const previousTargetY = this.cameraTarget.y;
    const previousTargetZ = this.cameraTarget.z;
    const step = advancePlanarCameraFollow(
      this.camera.position,
      this.cameraTarget,
      this.framedTarget,
      this.hipsAnchor,
      this.hipsWorldPosition,
      delta,
      12,
      this.snapCameraFollow,
    );
    this.snapCameraFollow = false;
    this.followTranslation.set(
      step.target.x - previousTargetX,
      step.target.y - previousTargetY,
      step.target.z - previousTargetZ,
    );
    this.cameraTarget.set(step.target.x, step.target.y, step.target.z);
    this.camera.position.set(step.cameraPosition.x, step.cameraPosition.y, step.cameraPosition.z);
    // Translate the user's possibly panned/orbited target by exactly the same root delta.
    this.controls.target.add(this.followTranslation);
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

  private publishStatus(status: ViewerStatus): void {
    this.contentStatus = status;
    if (!this.contextLost) this.emitStatus(status);
  }

  private emitStatus(status: ViewerStatus): void {
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
    this.emitStatus({ kind: "error", message: "WebGL 上下文已丢失；正在等待浏览器恢复预览" });
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

  private updateTelemetry(timestamp: DOMHighResTimeStamp): void {
    if (timestamp - this.lastTelemetryAt < TELEMETRY_INTERVAL_MS) return;
    this.lastTelemetryAt = timestamp;
    this.canvas.dataset.renderFrameCount = String(this.renderFrameCount);
    this.canvas.dataset.mixerTimeSeconds = String(this.mixer?.time ?? 0);
    this.canvas.dataset.renderCalls = String(this.renderer.info.render.calls);
    this.canvas.dataset.renderTriangles = String(this.renderer.info.render.triangles);
    this.canvas.dataset.renderGeometries = String(this.renderer.info.memory.geometries);
    this.canvas.dataset.renderTextures = String(this.renderer.info.memory.textures);
    if (!this.vrm || !this.hasCameraFraming) {
      this.canvas.dataset.avatarFullyVisible = "false";
      delete this.canvas.dataset.avatarProjectedBounds;
      return;
    }
    const hips = this.vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) {
      this.canvas.dataset.avatarFullyVisible = "false";
      delete this.canvas.dataset.avatarProjectedBounds;
      return;
    }
    hips.getWorldPosition(this.hipsWorldPosition);
    this.camera.updateWorldMatrix(true, false);
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let minZ = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let maxZ = Number.NEGATIVE_INFINITY;
    for (let mask = 0; mask < 8; mask += 1) {
      this.telemetryCorner.set(
        mask & 1 ? this.avatarBoundsRelativeToHips.max.x : this.avatarBoundsRelativeToHips.min.x,
        mask & 2 ? this.avatarBoundsRelativeToHips.max.y : this.avatarBoundsRelativeToHips.min.y,
        mask & 4 ? this.avatarBoundsRelativeToHips.max.z : this.avatarBoundsRelativeToHips.min.z,
      );
      this.telemetryCorner.add(this.hipsWorldPosition);
      this.projectedCorner.copy(this.telemetryCorner).project(this.camera);
      minX = Math.min(minX, this.projectedCorner.x);
      minY = Math.min(minY, this.projectedCorner.y);
      minZ = Math.min(minZ, this.projectedCorner.z);
      maxX = Math.max(maxX, this.projectedCorner.x);
      maxY = Math.max(maxY, this.projectedCorner.y);
      maxZ = Math.max(maxZ, this.projectedCorner.z);
    }
    const finite = [minX, minY, minZ, maxX, maxY, maxZ].every(Number.isFinite);
    const fullyVisible = finite
      && minX >= -1 && maxX <= 1
      && minY >= -1 && maxY <= 1
      && minZ >= -1 && maxZ <= 1;
    this.canvas.dataset.avatarProjectedBounds = JSON.stringify({ minX, minY, minZ, maxX, maxY, maxZ });
    this.canvas.dataset.avatarFullyVisible = String(fullyVisible);
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
    const delta = Math.min(this.timer.getDelta(), 0.1);
    this.mixer?.update(delta);
    this.vrm?.update(delta);
    this.followAvatarHips(delta);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.renderFrameCount += 1;
    this.updateTelemetry(timestamp);
    if (this.shouldRender()) this.frameHandle = requestAnimationFrame(this.tick);
  };
}
