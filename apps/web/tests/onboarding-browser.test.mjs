import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {createServer} from "vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", chromium.executablePath(),
].find(path => path && existsSync(path));

test("setup wizard saves without leaking keys, activates, lists voices and recovers deployment polling", {skip: !executablePath, timeout: 60_000}, async () => {
  const server = await createServer({configFile:false, root: resolve(import.meta.dirname, ".."), server: {host:"127.0.0.1", port:0}});
  await server.listen();
  const browser = await chromium.launch({executablePath, headless:true, args:["--mute-audio"]});
  try {
    const page = await browser.newPage({viewport:{width:1360,height:900}});
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    let transientFailure = false;
    const state = {
      providers:{deepseek:{name:"DeepSeek",kind:"language",base_url:"https://api.deepseek.com",model:"deepseek-chat"},
        "openai-speech":{name:"OpenAI Speech",kind:"speech",base_url:"https://api.openai.com/v1",model:"gpt-4o-mini-tts",voice:"alloy"}},
      active:{}, connections:[], jobs:[],
      recipes:[{id:"motioncraft",name:"MotionCraft",storage_gib:20,license_url:"https://github.com/cure-lab/MotionCraft"}],
    };
    await page.route("**/api/v1/onboarding**", async route => {
      const req = route.request(), path = new URL(req.url()).pathname.replace("/api/v1/onboarding", "");
      assert.equal(req.headers()["x-virea-setup"], "1");
      let result = state;
      if (path === "/discover") result = {platform:"Windows",architecture:"AMD64",free_disk_gib:100,data_directory:"local/home",services:[],vrchat_supported:true};
      else if (path === "/connections" && req.method() === "PUT") {
        const {api_key, ...row} = req.postDataJSON();
        const previous = state.connections.find(c => c.id === row.id);
        state.connections = state.connections.filter(c => c.id !== row.id);
        state.connections.push({...row,kind:state.providers[row.provider].kind,has_key:!!api_key || !!previous?.has_key});
      } else if (path.endsWith("/activate")) state.active[state.connections[0].kind] = state.connections[0].id;
      else if (path.endsWith("/voices")) result = {voices:[{id:"alloy",name:"Alloy"},{id:"nova",name:"Nova"}]};
      else if (path === "/deployments") {
        state.jobs = [{id:"job1",status:"running",step:3,total_steps:6,percent:33,stage_percent:42,message:"下载官方检查点",request:req.postDataJSON()}];
      } else if (path.endsWith("/cancel")) state.jobs[0].status = "cancelled";
      else if (transientFailure) {
        transientFailure = false;
        await route.fulfill({status:503,json:{detail:"temporarily offline"}}); return;
      }
      await route.fulfill({json:result});
    });
    await page.goto(server.resolvedUrls.local[0] + "setup.html");
    await page.locator("#provider option").first().waitFor({state:"attached"});
    await page.locator("#api-key").fill("dummy-browser-secret");
    await page.getByRole("button",{name:"保存连接",exact:true}).click();
    await page.getByText("密钥已保存",{exact:true}).waitFor();
    assert.equal(await page.locator("#api-key").inputValue(), "");
    assert.equal(await page.evaluate(() => JSON.stringify({...localStorage,...sessionStorage}).includes("dummy-browser-secret")),false);
    assert.equal((await page.content()).includes("dummy-browser-secret"),false);
    await page.getByRole("button",{name:"测试并启用"}).click();
    await page.getByText("使用中",{exact:true}).waitFor();
    await page.getByRole("tab",{name:"语音模型"}).click();
    await page.getByRole("button",{name:"读取声线列表"}).click();
    await page.waitForFunction(() => document.querySelectorAll("#voice-options option").length === 2);
    await page.locator("#license").check();
    await page.locator("#deploy-button").click();
    await page.getByText("33% · [3/6]",{exact:true}).waitFor();
    transientFailure = true;
    await page.getByText(/正在自动重连/).waitFor();
    state.jobs[0] = {...state.jobs[0],step:6,percent:100,status:"succeeded",message:"部署完成"};
    await page.getByText("已就绪",{exact:true}).waitFor();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    assert.equal(await page.locator("audio,video").count(),0);
    assert.deepEqual(errors,[]);
  } finally {await browser.close(); await server.close();}
});
