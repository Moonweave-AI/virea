import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

test("web client uses canonical /api/v1 and separates catalog visibility from runtime eligibility", () => {
  const api = fs.readFileSync(path.join(root, "src", "api.ts"), "utf8");
  const http = fs.readFileSync(path.join(root, "src", "http.ts"), "utf8");
  const contracts = fs.readFileSync(path.join(root, "src", "contracts.ts"), "utf8");
  const main = fs.readFileSync(path.join(root, "src", "main.ts"), "utf8");
  assert.match(http, /`\/api\/v1\$\{path\}`/);
  for (const status of ["registered", "runnable_upstream", "integrated_experimental", "supported", "blocked"]) {
    assert.match(api + main, new RegExp(status));
  }
  assert.match(main, /目录同时展示可执行模型与已核实但仍被上游完整性、许可或运行时阻断的模型/);
  assert.match(main, /只有具备真实 Worker 和 production acceptance 的条目才能安装/);
  assert.match(api, /createInstallPayload\(manifest, executionTarget\)/);
  assert.match(api, /createGenerationPayload\(manifest, prompt, seconds, seed, executionTarget\)/);
  assert.match(api, /"\/execution-domains"/);
  assert.match(api, /\/execution-options/);
  assert.match(main, /executionDomainSelector\("global-execution-domain"\)/);
  assert.equal([...main.matchAll(/executionDomainSelector\(/g)].length, 2);
  assert.match(main, /请选择运行环境后再安装或生成/);
  assert.doesNotMatch(api, /body:\s*JSON\.stringify\(\{\s*model_id/);
  assert.match(api, /\/jobs\/\$\{encodeURIComponent\(jobId\)\}\/result/);
  assert.doesNotMatch(api, /`\/jobs\/\$\{jobId\}/);
  assert.match(main, /Motion Studio 0\.4\.0/);
  assert.doesNotMatch(main, /Motion Studio 0\.3/);
  const bootstrap = main.slice(main.indexOf("async function bootstrap"), main.indexOf("void bootstrap"));
  assert.match(bootstrap, /api\.health\(\)/);
  assert.doesNotMatch(bootstrap, /api\.system\(\)/);
  assert.match(http, /new AbortController\(\)/);
  assert.match(http, /finally\s*\{/);
  assert.match(http, /clearTimeout\(timer\)/);
  assert.match(contracts, /runtime_core_epoch: string \| null/);
  assert.match(contracts, /execution_domain_id\?: string \| null/);
  assert.match(main, /runtime\.runtime_core_epoch/);
});

test("viewer loads VRM and VRMA through the official Pixiv loaders", () => {
  const source = fs.readFileSync(path.join(root, "src", "viewer.ts"), "utf8");
  assert.doesNotMatch(source, /MoMask.*quaternion|SentiAvatar.*pose|HY-Motion.*rotation/i);
  assert.match(source, /VRMLoaderPlugin/);
  assert.match(source, /VRMAnimationLoaderPlugin/);
  assert.match(source, /createVRMAnimationClip/);
  assert.match(source, /ensureVRMLookAtQuaternionProxy\(this\.vrm\)/);
  assert.match(source, /AnimationMixer/);
  assert.match(source, /new THREE\.Timer\(\)/);
  assert.match(source, /this\.timer\.update\(timestamp\)/);
  assert.doesNotMatch(source, /new THREE\.Clock\(\)/);
});

test("production assets stay under the FastAPI /app mount", () => {
  const config = fs.readFileSync(path.join(root, "vite.config.ts"), "utf8");
  assert.match(config, /base:\s*["']\/app\/["']/);
});
