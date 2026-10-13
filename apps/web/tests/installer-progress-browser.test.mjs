import test from "node:test";
import assert from "node:assert/strict";
import {existsSync, mkdirSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {createServer} from "./vite-fixture.mjs";
import tailwindcss from "@tailwindcss/vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", chromium.executablePath(),
].find(path => path && existsSync(path));

test("measured installer progress reaches both setup cards and updates without reloading", {skip:!executablePath,timeout:60_000}, async () => {
  const server = await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
  await server.listen();
  const browser = await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const now=Date.now();
    await page.clock.setFixedTime(new Date(now));
    const errors=[];
    page.on("pageerror",error=>errors.push(error.message));
    let process={phase:"download",file:"torch",percent:50,completed_bytes:536870912,total_bytes:1073741824,bytes_per_second:10485760,eta_seconds:51,updated_at:now/1000};
    const model={model:{id:"motion-test",display_name:"Motion model"},output:{skeleton_id:"smplx",representation_id:"axis-angle"},runtime_variants:[],capability:{installable:true}};
    await page.route("**/api/v1/**",async route=>{
      const path=new URL(route.request().url()).pathname;
      const payload=path==="/api/v1/models"?[model]:path.endsWith("/model-deployments")?[{model_id:"motion-test",status:"running",stage:"runtime",message:"Preparing the environment",process}]:{models:[]};
      await route.fulfill({json:payload});
    });
    await page.route("**/installer-test.html",route=>route.fulfill({contentType:"text/html",body:`<!doctype html><html><head><meta charset="utf-8"></head><body><div id="jobs"></div><div id="library"></div><script type="module">
      import '/src/setup.css';
      import {mountModelLibrary} from '/src/studio/model-library.tsx';
      mountModelLibrary(document.getElementById('library'));
    </script></body></html>`}));
    await page.goto(server.resolvedUrls.local[0]+"installer-test.html");
    const updateJob=async()=>page.evaluate(async process=>{
      const {showJobs}=await import('/src/studio/setup-panels.tsx');
      showJobs(document.getElementById('jobs'),[{id:"voice-test",status:"running",request:{recipe:"kokoro"},step:3,total_steps:6,percent:33,message:"Preparing the environment",process}],()=>"");
    },process);
    await updateJob();
    for (const language of ["en","zh-CN"]) {
      await page.evaluate(async language=>{const {setLanguage}=await import('/src/studio/preferences.ts');setLanguage(language);},language);
      const label=language==="en"?"Downloading dependencies":"下载依赖";
      for (const host of ["#jobs","#library"]) {
        const meter=page.locator(`${host} .mw-installer-meter`);
        await meter.getByText(label,{exact:true}).waitFor();
        assert.equal(await meter.getByRole("progressbar",{name:label}).getAttribute("aria-valuenow"),"50");
        assert.match(await meter.innerText(),/512.0 MiB \/ 1.00 GiB/);
        assert.match(await meter.innerText(),/10.0 MiB\/s/);
        assert.match(await meter.innerText(),/51s/);
      }
    }
    process={...process,percent:75,completed_bytes:805306368,updated_at:Date.now()/1000};
    await updateJob();
    for (const host of ["#jobs","#library"]) await page.locator(`${host} .mw-installer-meter`).getByText("75.0%",{exact:true}).waitFor();
    process={phase:"install",file:"torch",percent:40,completed:4,total:10,updated_at:Date.now()/1000};
    await updateJob();
    await page.locator('#library .mw-installer-meter').getByText("4/10 个依赖包",{exact:true}).waitFor();
    assert.doesNotMatch(await page.locator('#jobs .mw-installer-meter').innerText(),/MiB|GiB/);
    process={phase:"build",file:"extension",percent:null,updated_at:now/1000-30};
    await updateJob();
    const unknown=page.locator('#jobs .mw-installer-meter');
    assert.equal(await unknown.getByRole("progressbar").getAttribute("aria-valuenow"),null);
    await unknown.getByText("等待安装器下一条输出",{exact:true}).waitFor();
    await page.evaluate(async()=>{const {setLanguage}=await import('/src/studio/preferences.ts');setLanguage("en");});
    await unknown.getByText("Waiting for the installer's next update",{exact:true}).waitFor();
    const screenshot=resolve(import.meta.dirname,"../../../.virea-runtime/qa/installer-progress-en.png");
    mkdirSync(resolve(screenshot,".."),{recursive:true});
    await page.screenshot({path:screenshot,fullPage:true});
    assert.deepEqual(errors,[]);
  } finally {await browser.close();await server.close();}
});
