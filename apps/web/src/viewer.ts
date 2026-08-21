import * as THREE from "three";
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

export class RealVrmViewer {
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  private readonly renderer: THREE.WebGLRenderer;
  private readonly timer = new THREE.Timer();
  private readonly resizeObserver: ResizeObserver;
  private vrm: VRM | null = null;
  private animation: VRMAnimation | null = null;
  private mixer: THREE.AnimationMixer | null = null;
  private readonly framedTarget = new THREE.Vector3();
  private readonly cameraTarget = new THREE.Vector3();
  private readonly hipsAnchor = new THREE.Vector3();
  private readonly hipsWorldPosition = new THREE.Vector3();
  private readonly avatarSize = new THREE.Vector3();
  private readonly avatarBoundsRelativeToHips = new THREE.Box3();
  private readonly projectedCorner = new THREE.Vector3();
  private readonly telemetryCorner = new THREE.Vector3();
  private hasCameraFraming = false;
  private snapCameraFollow = false;
  private frameHandle = 0;
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
    this.scene.add(key);
    this.scene.add(new THREE.GridHelper(10, 20, 0x34506a, 0x17202c));
    this.camera.position.set(0, 1.25, 3.6);
    this.camera.lookAt(0, 1, 0);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.canvas.dataset.vireaViewerTelemetry = "virea.viewer_telemetry.v1.0.0";
    this.canvas.dataset.viewerState = "idle";
    this.canvas.dataset.webglContextLost = "false";
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
    this.canvas.addEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.addEventListener("webglcontextrestored", this.markWebglContextRestored);
    this.resize();
    this.timer.connect(document);
    this.frameHandle = requestAnimationFrame(this.tick);
  }

  public async loadAvatarFile(file: File): Promise<void> {
    if (!/\.(vrm|glb)$/i.test(file.name)) throw new Error("Avatar 必须是包含 VRM 扩展的 .vrm 或 .glb 文件");
    if (this.avatarObjectUrl) URL.revokeObjectURL(this.avatarObjectUrl);
    this.avatarObjectUrl = URL.createObjectURL(file);
    await this.loadAvatar(this.avatarObjectUrl);
  }

  public async loadAnimationFile(file: File): Promise<void> {
    if (!/\.vrma$/i.test(file.name)) throw new Error("动作文件必须是 .vrma");
    if (this.animationObjectUrl) URL.revokeObjectURL(this.animationObjectUrl);
    this.animationObjectUrl = URL.createObjectURL(file);
    await this.loadAnimation(this.animationObjectUrl);
  }

  public async loadAnimation(url: string): Promise<void> {
    this.publishStatus({ kind: "loading", message: "正在读取真实 VRMA…" });
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMAnimationLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const animations = gltf.userData.vrmAnimations as VRMAnimation[] | undefined;
    if (!animations?.length) throw new Error("文件不含 VRMC_vrm_animation 数据");
    this.animation = animations[0] ?? null;
    this.bindAndPlay();
  }

  public play(): void {
    if (!this.vrm) throw new Error("请先加载 VRM Avatar");
    if (!this.animation) throw new Error("请先加载真实 VRMA 动作");
    this.bindAndPlay();
  }

  public dispose(): void {
    cancelAnimationFrame(this.frameHandle);
    this.timer.dispose();
    this.resizeObserver.disconnect();
    this.mixer?.stopAllAction();
    if (this.vrm) VRMUtils.deepDispose(this.vrm.scene);
    this.renderer.dispose();
    this.canvas.removeEventListener("webglcontextlost", this.markWebglContextLost);
    this.canvas.removeEventListener("webglcontextrestored", this.markWebglContextRestored);
    if (this.avatarObjectUrl) URL.revokeObjectURL(this.avatarObjectUrl);
    if (this.animationObjectUrl) URL.revokeObjectURL(this.animationObjectUrl);
  }

  private async loadAvatar(url: string): Promise<void> {
    this.publishStatus({ kind: "loading", message: "正在解析 VRM Avatar…" });
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm as VRM | undefined;
    if (!vrm) throw new Error("该 GLB 不含 VRM humanoid 扩展，不能应用 VRMA");
    if (this.vrm) {
      this.scene.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
    }
    this.vrm = vrm;
    VRMUtils.removeUnnecessaryVertices(vrm.scene);
    VRMUtils.combineSkeletons(vrm.scene);
    VRMUtils.rotateVRM0(vrm);
    this.scene.add(vrm.scene);
    this.frameAvatar();
    if (this.animation) this.bindAndPlay();
    else this.publishStatus({ kind: "ready", message: "Avatar 已加载；请选择或载入 VRMA" });
  }

  private bindAndPlay(): void {
    if (!this.vrm || !this.animation) {
      this.publishStatus({ kind: "ready", message: "VRMA 已加载；载入 Avatar 后即可播放" });
      return;
    }
    this.mixer?.stopAllAction();
    this.mixer = new THREE.AnimationMixer(this.vrm.scene);
    this.mixer.addEventListener("loop", () => {
      // Root locomotion clips jump back to their first keyframe when looping.
      // Snap only on that discontinuity so the Avatar cannot outrun a camera
      // that is intentionally smooth during ordinary motion.
      this.snapCameraFollow = true;
    });
    assertUsableAnimationRestHips(this.animation);
    ensureVRMLookAtQuaternionProxy(this.vrm);
    const clip = createVRMAnimationClip(this.animation, this.vrm);
    if (clip.tracks.length === 0) throw new Error("VRMA 与该 Avatar 没有可播放的 humanoid track");
    assertFiniteClip(clip);
    this.snapCameraFollow = true;
    this.mixer.clipAction(clip).reset().play();
    this.publishStatus({ kind: "playing", message: "正在播放真实 VRMA", duration: clip.duration });
  }

  private frameAvatar(): void {
    if (!this.vrm) return;
    this.vrm.scene.updateWorldMatrix(true, true);
    const box = new THREE.Box3().setFromObject(this.vrm.scene);
    if (box.isEmpty()) throw new Error("Avatar 没有可渲染的几何体");
    const center = box.getCenter(new THREE.Vector3());
    box.getSize(this.avatarSize);
    const hips = this.vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) throw new Error("Avatar 缺少 humanoid hips，无法建立根位移相机跟随");
    hips.getWorldPosition(this.hipsAnchor);
    this.avatarBoundsRelativeToHips.copy(box);
    this.avatarBoundsRelativeToHips.min.sub(this.hipsAnchor);
    this.avatarBoundsRelativeToHips.max.sub(this.hipsAnchor);
    this.framedTarget.copy(center);
    this.cameraTarget.copy(center);
    this.hasCameraFraming = true;
    this.applyCameraFraming();
  }

  private applyCameraFraming(): void {
    if (!this.hasCameraFraming) return;
    const aspect = Math.max(this.canvas.clientWidth, 1) / Math.max(this.canvas.clientHeight, 1);
    const framing = computeCameraFraming(
      this.avatarSize.x,
      this.avatarSize.y,
      this.avatarSize.z,
      aspect,
      THREE.MathUtils.degToRad(this.camera.fov),
    );
    this.camera.near = framing.near;
    this.camera.far = framing.far;
    this.camera.position.set(this.cameraTarget.x, this.cameraTarget.y, this.cameraTarget.z + framing.distance);
    this.camera.lookAt(this.cameraTarget);
    this.camera.updateProjectionMatrix();
  }

  private followAvatarHips(delta: number): void {
    if (!this.vrm || !this.hasCameraFraming) return;
    const hips = this.vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) return;
    hips.getWorldPosition(this.hipsWorldPosition);
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
    this.cameraTarget.set(step.target.x, step.target.y, step.target.z);
    this.camera.position.set(step.cameraPosition.x, step.cameraPosition.y, step.cameraPosition.z);
    this.camera.lookAt(this.cameraTarget);
  }

  private resize(): void {
    const width = Math.max(this.canvas.clientWidth, 1);
    const height = Math.max(this.canvas.clientHeight, 1);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.applyCameraFraming();
    if (!this.hasCameraFraming) this.camera.updateProjectionMatrix();
  }

  private publishStatus(status: ViewerStatus): void {
    this.canvas.dataset.viewerState = status.kind;
    this.canvas.dataset.viewerMessage = status.message;
    if (status.duration == null) delete this.canvas.dataset.viewerDurationSeconds;
    else this.canvas.dataset.viewerDurationSeconds = String(status.duration);
    this.onStatus(status);
  }

  private markWebglContextLost = (): void => {
    this.canvas.dataset.webglContextLost = "true";
  };

  private markWebglContextRestored = (): void => {
    this.canvas.dataset.webglContextLost = "false";
  };

  private updateTelemetry(): void {
    const frameCount = Number(this.canvas.dataset.renderFrameCount ?? "0") + 1;
    this.canvas.dataset.renderFrameCount = String(frameCount);
    this.canvas.dataset.mixerTimeSeconds = String(this.mixer?.time ?? 0);
    this.canvas.dataset.renderCalls = String(this.renderer.info.render.calls);
    this.canvas.dataset.renderTriangles = String(this.renderer.info.render.triangles);
    if (!this.vrm || !this.hasCameraFraming) {
      this.canvas.dataset.avatarFullyVisible = "false";
      return;
    }
    const hips = this.vrm.humanoid.getRawBoneNode(VRMHumanBoneName.Hips);
    if (!hips) {
      this.canvas.dataset.avatarFullyVisible = "false";
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

  private tick = (timestamp: DOMHighResTimeStamp): void => {
    this.timer.update(timestamp);
    const delta = Math.min(this.timer.getDelta(), 0.1);
    this.mixer?.update(delta);
    this.vrm?.update(delta);
    this.followAvatarHips(delta);
    this.renderer.render(this.scene, this.camera);
    this.updateTelemetry();
    this.frameHandle = requestAnimationFrame(this.tick);
  };
}
