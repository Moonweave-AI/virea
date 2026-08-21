import type * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { VRMLookAtQuaternionProxy, type VRMAnimation } from "@pixiv/three-vrm-animation";

const MIN_REST_HIPS_HEIGHT = 1e-3;
const LOOK_AT_PROXY_NAME = "VRMLookAtQuaternionProxy";

/**
 * three-vrm-animation binds look-at quaternion tracks through a proxy object
 * that must be a direct child of the VRM scene. Register it explicitly so clip
 * construction never has to mutate the Avatar implicitly. Avatars without a
 * VRM look-at component intentionally need no proxy or look-at track.
 */
export function ensureVRMLookAtQuaternionProxy(
  vrm: Pick<VRM, "lookAt" | "scene">,
): VRMLookAtQuaternionProxy | null {
  if (!vrm.lookAt) return null;

  let proxy = vrm.scene.children.find(
    (child): child is VRMLookAtQuaternionProxy => child instanceof VRMLookAtQuaternionProxy,
  );
  if (!proxy) {
    proxy = new VRMLookAtQuaternionProxy(vrm.lookAt);
    vrm.scene.add(proxy);
  }
  proxy.name = LOOK_AT_PROXY_NAME;
  return proxy;
}

/**
 * three-vrm-animation scales hips translation by
 * `avatarRestHipsHeight / animationRestHipsHeight`. A zero source height would
 * turn an otherwise finite motion into Infinity/NaN, so reject the malformed
 * producer artifact before binding instead of hiding it with camera behavior.
 */
export function assertUsableAnimationRestHips(animation: VRMAnimation): void {
  const animationHeight = animation.restHipsPosition.y;
  if (!Number.isFinite(animationHeight) || animationHeight < MIN_REST_HIPS_HEIGHT) {
    throw new Error("VRMA 的 hips rest height 缺失或为零；拒绝生成非有限位移动画");
  }
}

export function assertFiniteClip(clip: THREE.AnimationClip): void {
  const invalidTrack = clip.tracks.find((track) => Array.from(track.values).some((value) => !Number.isFinite(value)));
  if (invalidTrack) {
    throw new Error(`VRMA 绑定产生非有限数值：${invalidTrack.name}`);
  }
}

export interface CameraFraming {
  distance: number;
  near: number;
  far: number;
}

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export interface CameraFollowStep {
  cameraPosition: Point3;
  target: Point3;
}

/**
 * Follow the Avatar's real hips displacement in the ground plane without
 * touching the motion itself. The framed target owns the vertical composition,
 * so gait bounce and jumps cannot make the camera crop the feet or head. Camera
 * and target receive the exact same translation, preserving their relative
 * offset and therefore the established framing/FOV.
 */
export function advancePlanarCameraFollow(
  cameraPosition: Readonly<Point3>,
  currentTarget: Readonly<Point3>,
  framedTarget: Readonly<Point3>,
  anchorHips: Readonly<Point3>,
  currentHips: Readonly<Point3>,
  deltaSeconds: number,
  responsiveness = 12,
  snap = false,
): CameraFollowStep {
  const points = [cameraPosition, currentTarget, framedTarget, anchorHips, currentHips];
  if (
    points.some((point) => [point.x, point.y, point.z].some((value) => !Number.isFinite(value))) ||
    !Number.isFinite(deltaSeconds) ||
    deltaSeconds < 0 ||
    !Number.isFinite(responsiveness) ||
    responsiveness <= 0
  ) {
    throw new Error("Viewer 相机跟随输入无效");
  }

  const desiredTarget = {
    x: framedTarget.x + currentHips.x - anchorHips.x,
    y: framedTarget.y,
    z: framedTarget.z + currentHips.z - anchorHips.z,
  };
  const alpha = snap ? 1 : 1 - Math.exp(-responsiveness * deltaSeconds);
  const target = {
    x: currentTarget.x + (desiredTarget.x - currentTarget.x) * alpha,
    y: framedTarget.y,
    z: currentTarget.z + (desiredTarget.z - currentTarget.z) * alpha,
  };
  const translation = {
    x: target.x - currentTarget.x,
    y: target.y - currentTarget.y,
    z: target.z - currentTarget.z,
  };
  return {
    cameraPosition: {
      x: cameraPosition.x + translation.x,
      y: cameraPosition.y + translation.y,
      z: cameraPosition.z + translation.z,
    },
    target,
  };
}

export function computeCameraFraming(
  width: number,
  height: number,
  depth: number,
  aspect: number,
  verticalFovRadians: number,
  margin = 1.2,
): CameraFraming {
  const values = [width, height, depth, aspect, verticalFovRadians, margin];
  if (values.some((value) => !Number.isFinite(value)) || width <= 0 || height <= 0 || depth < 0 || aspect <= 0) {
    throw new Error("Avatar 包围盒或 Viewer 尺寸无效，无法计算相机视锥");
  }
  if (verticalFovRadians <= 0 || verticalFovRadians >= Math.PI || margin < 1) {
    throw new Error("Viewer 相机 FOV 或 framing margin 无效");
  }

  const horizontalFov = 2 * Math.atan(Math.tan(verticalFovRadians / 2) * aspect);
  const verticalDistance = height / 2 / Math.tan(verticalFovRadians / 2);
  const horizontalDistance = width / 2 / Math.tan(horizontalFov / 2);
  const distance = Math.max(verticalDistance, horizontalDistance) * margin + depth / 2;
  return {
    distance,
    near: Math.max(distance / 100, 0.01),
    far: Math.max(distance * 100, 100),
  };
}
