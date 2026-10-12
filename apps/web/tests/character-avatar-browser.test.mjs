import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {createServer} from "vite";
import tailwindcss from "@tailwindcss/vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium", chromium.executablePath(),
].find(path => path && existsSync(path));

// A small self-contained VRM humanoid, authored for this regression test.
function avatarFixture() {
  const nodes = [], humanBones = {};
  const bone = (name, translation, parent) => {
    const index = nodes.length; nodes.push({name, translation, children:[]}); humanBones[name] = {node:index};
    if (parent) nodes[humanBones[parent].node].children.push(index);
  };
  bone("hips", [0,1,0]); bone("spine", [0,0.2,0], "hips"); bone("head", [0,0.4,0], "spine");
  for (const [side,sign] of [["left",1],["right",-1]]) {
    bone(`${side}UpperArm`, [sign*0.2,0.3,0], "spine");
    bone(`${side}LowerArm`, [sign*0.25,0,0], `${side}UpperArm`);
    bone(`${side}Hand`, [sign*0.2,0,0], `${side}LowerArm`);
    bone(`${side}UpperLeg`, [sign*0.1,-0.1,0], "hips");
    bone(`${side}LowerLeg`, [0,-0.4,0], `${side}UpperLeg`);
    bone(`${side}Foot`, [0,-0.4,0], `${side}LowerLeg`);
  }
  const positions = new Float32Array([-0.3,0,0, 0.3,0,0, 0,1.7,0]);
  const meshIndex = nodes.length; nodes.push({mesh:0});
  return Buffer.from(JSON.stringify({asset:{version:"2.0"},scene:0,scenes:[{nodes:[0,meshIndex]}],nodes,
    buffers:[{byteLength:positions.byteLength,uri:`data:application/octet-stream;base64,${Buffer.from(positions.buffer).toString("base64")}`}],
    bufferViews:[{buffer:0,byteLength:positions.byteLength}],
    accessors:[{bufferView:0,componentType:5126,count:3,type:"VEC3",min:[-0.3,0,0],max:[0.3,1.7,0]}],
    meshes:[{primitives:[{attributes:{POSITION:0}}]}],extensionsUsed:["VRMC_vrm"],extensions:{VRMC_vrm:{specVersion:"1.0",
      meta:{name:"Standalone avatar",authors:["VIREA tests"],licenseUrl:"https://vrm.dev/licenses/1.0/"},humanoid:{humanBones}}},
  }));
}

test("VRM imports independently of unavailable, unconfigured or pending model services", {skip:!executablePath,timeout:90_000}, async () => {
  const server = await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
  await server.listen();
  const browser = await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
  try {
    for (const scenario of ["offline", "unconfigured", "pending"]) {
      const page = await browser.newPage();
      const calls = [], errors = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.route("**/api/v1/**", route => {
        const path = new URL(route.request().url()).pathname; calls.push(path);
        if (path.endsWith("/motion-backends")) {
          if (scenario === "pending") return;
          if (scenario === "unconfigured") return route.fulfill({json:{default:"motioncraft",backends:[{id:"motioncraft",name:"MotionCraft",configured:false,ready:false}]}});
        }
        return route.fulfill({status:503,json:{detail:"Model service offline"}});
      });
      await page.goto(server.resolvedUrls.local[0]+"character.html", {waitUntil:"domcontentloaded"});
      await page.locator("#avatar").setInputFiles({name:"standalone.vrm",mimeType:"model/gltf+json",buffer:avatarFixture()});
      await page.waitForFunction(() => document.querySelector("#character").classList.contains("avatar-loaded"), null, {timeout:15_000});
      assert.equal(await page.locator("#avatar-name").textContent(), "standalone");
      assert.equal(await page.locator("#start").isEnabled(), true);
      assert.equal(calls.some(path => path.endsWith("neutral-pose") || path.includes("/deployments")), false);
      assert.deepEqual(errors, []);
      await page.close();
    }
    const page = await browser.newPage();
    await page.route("**/api/v1/**", route => route.fulfill({status:503,json:{detail:"Model service offline"}}));
    await page.goto(server.resolvedUrls.local[0]+"character.html");
    const rotations = await page.evaluate(async () => {
      const THREE = await import("/node_modules/three/build/three.module.js");
      const {RelaxedIdle} = await import("/src/character/idle.ts");
      return ["0", "1"].map(metaVersion => {
        const bones = Object.fromEntries(["hips","leftUpperArm","rightUpperArm"].map(name => [name,new THREE.Object3D()]));
        bones.hips.position.set(2,1,-3);
        new RelaxedIdle({meta:{metaVersion},humanoid:{getNormalizedBoneNode:name=>bones[name]}});
        return {root:bones.hips.position.toArray(),left:bones.leftUpperArm.quaternion.toArray(),right:bones.rightUpperArm.quaternion.toArray()};
      });
    });
    for (const pose of rotations) {
      assert.deepEqual(pose.root,[2,1,-3]);
      assert.ok(Math.abs(pose.left.reduce((sum,x)=>sum+x*x,0)-1)<1e-10);
      assert.equal(pose.left[2],-pose.right[2]);
    }
    assert.equal(rotations[0].left[2],-rotations[1].left[2],"VRM 0 uses its own coordinate convention");
  } finally {await browser.close();await server.close();}
});
