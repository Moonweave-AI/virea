import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
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

test("model library distinguishes local verification, reuse and network transfers in both languages", {skip:!executablePath,timeout:60_000}, async () => {
  const server = await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
  await server.listen();
  const browser = await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const phases = [
      ["verify-local","本地校验","Local verification"],
      ["integrity","本地校验","Local verification"],
      ["reuse","本地复用","Local reuse"],
      ["download","网络下载","Network download"],
      ["reconstruction","本地重建","Local reconstruction"],
    ];
    const models = phases.map(([phase])=>({model:{id:phase,display_name:phase},output:{skeleton_id:"smplx",representation_id:"axis-angle"},runtime_variants:[],capability:{installable:true}}));
    const progress = phases.map(([phase])=>({model_id:phase,status:"running",stage:"download",message:"校验已有模型文件，下载缺少的权重",transfer:{artifact_id:"weights",phase,completed_bytes:512,total_bytes:1024}}));
    models.push({model:{id:"environment",display_name:"environment"},output:{skeleton_id:"smplx",representation_id:"axis-angle"},runtime_variants:[],capability:{installable:true}});
    progress.push({model_id:"environment",status:"running",stage:"validate",message:"Preparing the environment",transfer:null});
    models.push({...models[0],model:{id:"ready-model",display_name:"Ready model"},installation:{ready:true,state:"READY"}});
    progress.push({...progress[0],model_id:"ready-model"});
    await page.route("**/api/v1/**", async route => {
      const path = new URL(route.request().url()).pathname;
      const payload = path === "/api/v1/models" ? models : path.endsWith("/model-deployments") ? progress : {models:[]};
      await route.fulfill({json:payload});
    });
    // Mount the actual Set Up library without unrelated provider/service side effects.
    await page.route("**/progress-test.html", route => route.fulfill({contentType:"text/html",body:`<!doctype html><html><head><meta charset="utf-8"></head><body><div id="library"></div><script type="module">
      import {mountModelLibrary} from '/src/studio/model-library.tsx';
      mountModelLibrary(document.getElementById('library'));
    </script></body></html>`}));
    await page.goto(server.resolvedUrls.local[0]+"progress-test.html");
    for (const language of ["zh-CN","en"]) {
      await page.evaluate(async language => {
        const {setLanguage} = await import('/src/studio/preferences.ts');
        setLanguage(language);
      },language);
      for (const [phase,zh,en] of phases) {
        const card = page.locator(`[data-model-id="${phase}"]`);
        const label = language === "en" ? en : zh;
        await card.getByText(label,{exact:true}).waitFor();
        const bar = card.getByRole("progressbar",{name:label+(language === "en" ? " progress" : "进度"),exact:true});
        assert.equal(await bar.getAttribute("aria-valuenow"),"50");
        if (phase !== "download") assert.doesNotMatch(await card.locator(".mw-model-progress").innerText(),/下载|download/i);
      }
      const preparing = page.locator('[data-model-id="environment"]');
      const bar = preparing.getByRole("progressbar",{name:language === "en" ? "Deployment progress" : "部署进度",exact:true});
      assert.equal(await bar.getAttribute("aria-valuenow"),null);
      // The installation database is authoritative if the final progress write failed.
      const ready = page.locator('[data-model-id="ready-model"]');
      await ready.getByText(language === "en" ? "Ready" : "已就绪",{exact:true}).waitFor();
      assert.equal(await ready.getByRole("progressbar").count(),0);
      assert.equal(await ready.getByRole("button",{name:language === "en" ? "Manage" : "管理",exact:true}).isEnabled(),true);
    }
    assert.deepEqual(errors,[]);
  } finally {await browser.close();await server.close();}
});
