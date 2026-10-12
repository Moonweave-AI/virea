import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {createServer} from "vite";
import tailwindcss from "@tailwindcss/vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", chromium.executablePath(),
].find(path => path && existsSync(path));

test("setup wizard saves without leaking keys, activates, lists voices and recovers deployment polling", {skip: !executablePath, timeout: 60_000}, async () => {
  const server = await createServer({configFile:false, plugins:[tailwindcss()], root: resolve(import.meta.dirname, ".."), server: {host:"127.0.0.1", port:0}});
  await server.listen();
  const browser = await chromium.launch({executablePath, headless:true, args:["--mute-audio"]});
  try {
    const page = await browser.newPage({viewport:{width:1360,height:900}});
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    let transientFailure = false;
    let speechOffline = false;
    const state = {
      providers:{deepseek:{name:"DeepSeek",kind:"language",base_url:"https://api.deepseek.com",model:"deepseek-chat"},
        "openai-speech":{name:"OpenAI Speech",kind:"speech",base_url:"https://api.openai.com/v1",model:"gpt-4o-mini-tts",voice:"alloy"},
        "local-speech":{name:"本地语音",kind:"speech",base_url:"http://127.0.0.1:8081/v1",model:"kokoro",local:true}},
      active:{}, connections:[], jobs:[],
      recipes:[{id:"motioncraft",name:"MotionCraft",storage_gib:20,license_url:"https://github.com/cure-lab/MotionCraft"}],
    };
    await page.route("**/api/v1/onboarding**", async route => {
      const req = route.request(), path = new URL(req.url()).pathname.replace("/api/v1/onboarding", "");
      assert.equal(req.headers()["x-virea-setup"], "1");
      let result = state;
      if (path === "/activity") result = {events:[],cursor:0,reset:false};
      else if (path === "/model-deployments") result = [];
      else if (path === "/model-library") result = {models:[]};
      else if (path === "/environments") result = {virea_home:"local/home",domains:[],conda:{environments:[]},runtimes:[]};
      else if (path === "/discover") result = {platform:"Windows",architecture:"AMD64",free_disk_gib:100,data_directory:"local/home",services:[],vrchat_supported:true};
      else if (path === "/resolve") {
        const draft = req.postDataJSON();
        if (draft.provider === "local-speech") {
          await route.fulfill(speechOffline ? {status:409,json:{detail:"没有检测到正在运行的本地语音服务"}} : {
            json:{base_url:"http://127.0.0.1:8083/v1",models:[{id:"audio8/tts-0.6b",name:"Audio8"}],
              voices:[{id:"clone-current",name:"我的克隆声线"}],model:"audio8/tts-0.6b",voice:"clone-current",tested:false}});
          return;
        }
        const speech = draft.provider === "openai-speech";
        result = {models:speech ? [{id:"gpt-4o-mini-tts",name:"GPT TTS"}] : [{id:"deepseek-chat",name:"DeepSeek Chat"},{id:"another-chat",name:"Another Chat"}],
          voices:speech ? [{id:"alloy",name:"Alloy"},{id:"nova",name:"Nova"}] : [],
          model:speech ? "gpt-4o-mini-tts" : "deepseek-chat",voice:speech ? "alloy" : "",tested:false};
      } else if (path === "/connections" && req.method() === "PUT") {
        const {api_key, ...row} = req.postDataJSON();
        const previous = state.connections.find(c => c.id === row.id);
        state.connections = state.connections.filter(c => c.id !== row.id);
        state.connections.push({...row,kind:state.providers[row.provider].kind,has_key:!!api_key || !!previous?.has_key});
      } else if (path.endsWith("/activate")) {
        const row = state.connections.find(c => path.includes(`/${c.id}/`));
        state.active[row.kind] = row.id;
        row.verification = {generated:true,kind:row.kind,model:row.model,verified_at:"2026-10-11T01:00:00Z",elapsed_seconds:1,
          result:row.kind === "language" ? {ready:true} : undefined,seconds:1,bytes:16044,waveform:[0.2,0.5,0.1],
          sample_text:"你好，这是一条真实生成的语音检验。",format:row.kind === "speech" ? "wav" : "json",
          artifact_url:"/api/v1/onboarding/verification/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/artifact"};
      }
      else if (path.endsWith("/voices")) result = {voices:[{id:"alloy",name:"Alloy"},{id:"nova",name:"Nova"}]};
      else if (path === "/deployments") {
        state.jobs = [{id:"job1",status:"running",step:3,total_steps:6,percent:33,stage_percent:42,message:"下载官方检查点",request:req.postDataJSON()}];
      } else if (path.endsWith("/cancel")) state.jobs[0].status = "cancelled";
      else if (transientFailure && path === "") {
        transientFailure = false;
        await route.fulfill({status:503,json:{detail:"temporarily offline"}}); return;
      }
      await route.fulfill({json:result});
    });
    await page.route("**/api/v1/models**", route=>route.fulfill({json:[]}));
    async function select(id, label) {
      await page.locator(`[data-native-select="${id}"]`).click();
      await page.getByRole("option",{name:label,exact:true}).click();
    }
    await page.goto(server.resolvedUrls.local[0] + "setup.html");
    await page.locator("#provider option").first().waitFor({state:"attached"});
    await page.locator("#api-key").fill("dummy-browser-secret");
    assert.equal(await page.locator("#model").evaluate(e => e.tagName), "SELECT");
    assert.equal(await page.locator("#voice").evaluate(e => e.tagName), "SELECT");
    assert.equal(await page.locator("#ollama-model").evaluate(e => e.tagName), "SELECT");
    await page.getByRole("button",{name:"自动检测并启用",exact:true}).click();
    await page.getByText("密钥已保存",{exact:true}).waitFor();
    assert.equal(await page.locator("#api-key").inputValue(), "");
    assert.equal(await page.evaluate(() => JSON.stringify({...localStorage,...sessionStorage}).includes("dummy-browser-secret")),false);
    assert.equal((await page.content()).includes("dummy-browser-secret"),false);
    await page.getByText("使用中",{exact:true}).waitFor();
    await page.locator("#saved-connections .verification summary").click();
    await page.getByText('{"ready":true}',{exact:true}).waitFor();
    await page.getByRole("tab",{name:"语音模型"}).click();
    await page.getByRole("button",{name:"重新检测可选项"}).click();
    await page.waitForFunction(() => document.querySelectorAll("#voice option").length === 2);
    assert.equal(await page.locator("#voice").inputValue(), "alloy");
    await select("voice", "Nova");
    await page.getByRole("button",{name:"自动检测并启用",exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll(".badge").length >= 2);
    assert.equal(state.connections.find(c => c.kind === "speech").voice, "nova");
    await page.locator("#saved-connections .saved").filter({hasText:"OpenAI Speech"}).locator(".verification summary").click();
    await page.getByText(/16044 bytes · 未播放声音/).waitFor();
    assert.equal(await page.getByRole("img",{name:"实际生成音频的振幅"}).count(),1);
    speechOffline = true;
    await select("provider", "本地语音");
    await page.getByText("没有检测到正在运行的本地语音服务",{exact:true}).waitFor();
    assert.match(await page.locator("#form-status").textContent(), /检测未完成/);
    assert.equal(await page.locator("#voice").inputValue(), "");
    assert.equal(state.active.speech, "openai-speech");
    speechOffline = false;
    await page.getByRole("button",{name:"重新检测可选项"}).click();
    await page.waitForFunction(() => document.querySelector("#voice").value === "clone-current");
    assert.equal(await page.locator("#base-url").inputValue(), "http://127.0.0.1:8083/v1");
    assert.equal(await page.locator("#notice").isHidden(), true);
    await page.getByRole("button",{name:"自动检测并启用",exact:true}).click();
    await page.waitForFunction(() => document.querySelectorAll(".badge").length === 2 && document.querySelector("#form-status").textContent === "已就绪");
    assert.equal(state.connections.find(c => c.id === "local-speech").base_url, "http://127.0.0.1:8083/v1");
    assert.equal(state.connections.find(c => c.id === "local-speech").voice, "clone-current");
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
