import * as THREE from "three";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {VRMLoaderPlugin, VRMUtils, type VRM} from "@pixiv/three-vrm";

/** A local model preview, never a claim to observe the game's skeletal pose. */
export async function avatarPreview(canvas: HTMLCanvasElement): Promise<() => void> {
  const loader = new GLTFLoader();
  loader.register(parser => new VRMLoaderPlugin(parser));
  const gltf = await loader.loadAsync("/api/v1/vrchat/avatar-preview");
  const vrm = gltf.userData.vrm as VRM | undefined;
  if (!vrm) { VRMUtils.deepDispose(gltf.scene); throw new Error("模型没有 VRM humanoid 数据"); }
  let renderer: THREE.WebGLRenderer;
  try { renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true}); }
  catch (error) { VRMUtils.deepDispose(vrm.scene); throw error; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7a8c84, 2));
  const light = new THREE.DirectionalLight(0xffffff, 1.4); light.position.set(2, 3, 4); scene.add(light);
  VRMUtils.rotateVRM0(vrm);
  // three-vrm's normalized left arm extends along -X; lower it around +Z.
  vrm.humanoid.getNormalizedBoneNode("leftUpperArm")?.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI * .36);
  vrm.humanoid.getNormalizedBoneNode("rightUpperArm")?.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), -Math.PI * .36);
  vrm.update(0); scene.add(vrm.scene); scene.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(vrm.scene);
  const center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3());
  const camera = new THREE.PerspectiveCamera(34, 1, .01, 100);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true; controls.enablePan = false; controls.enableZoom = false; controls.target.copy(center);
  const resize = new ResizeObserver(() => {
    const width = Math.max(1, canvas.clientWidth), height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false); camera.aspect = width / height;
    const extent = Math.max(size.y, size.x / camera.aspect);
    camera.position.copy(center).add(new THREE.Vector3(0, .04, extent / (2 * Math.tan(THREE.MathUtils.degToRad(17))) * 1.15));
    camera.updateProjectionMatrix(); controls.update();
  });
  resize.observe(canvas);
  let frame = 0, previous = 0, visible = true;
  const observer = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; }); observer.observe(canvas);
  const draw = (now: number) => {
    frame = requestAnimationFrame(draw);
    if (!visible || document.hidden || now - previous < 33) return;
    vrm.update(Math.min((now - previous) / 1000, .1)); previous = now; controls.update(); renderer.render(scene, camera);
  };
  frame = requestAnimationFrame(draw);
  return () => { cancelAnimationFrame(frame); observer.disconnect(); resize.disconnect(); controls.dispose(); renderer.dispose(); VRMUtils.deepDispose(vrm.scene); };
}
