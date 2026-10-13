import test, {before, after} from "node:test";
import assert from "node:assert/strict";
import {existsSync, mkdirSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {preview} from "vite";
import {createServer} from "./vite-fixture.mjs";
import tailwindcss from "@tailwindcss/vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome", "/usr/bin/chromium", chromium.executablePath(),
].find(path => path && existsSync(path));
let server, browser;
before(async () => {
  if (!executablePath) return;
  if (process.env.VIREA_LAYOUT_DIST) {
    server = await preview({configFile:false,base:"/app/",build:{outDir:process.env.VIREA_LAYOUT_DIST},preview:{host:"127.0.0.1",port:0}});
  } else {
    server = await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
    await server.listen();
  }
  browser = await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
});
after(async () => {
  await browser?.close();
  if (server?.close) await server.close();
  else if (server?.httpServer) await new Promise(resolve => server.httpServer.close(resolve));
});

const longModel = "prism-tp2m-1-4b-with-a-long-model-and-checkpoint-name";
const models = [{model:{id:longModel,display_name:longModel,status:"integrated_experimental",tasks:["text_to_motion"],adapter_family:"humanml3d-motion263-body22"},
  inputs:[{schema_version:"virea.job_request.v1.0.0",task:"text_to_motion",fields:{prompt:{type:"string",required:true},seconds:{type:"number",default:4},seed:{type:"integer",default:3407}}}],
  output:{skeleton_id:"humanml3d.body22.v1",representation_id:"humanml3d.vector263.v1"},
  runtime_variants:[{id:"cpu",availability:"ready",entrypoint_argv:["motion-worker"]}],capability:{installable:true},installation:{ready:true,state:"READY"},
  production_acceptance:{schema_version:"virea.production_e2e_acceptance.v1.0.0",kind:"production_e2e",timeout_seconds:30,
    request:{schema_version:"virea.job_request.v1.0.0",model_id:longModel,task:"text_to_motion",input:{prompt:"A person waves with the right hand."},parameters:{seconds:4,seed:3407},avatar_id:null,idempotency_key:null}}}];
const jobs = ["SUCCEEDED","FAILED","CANCELLED"].map((state,i)=>({id:`layout-job-${i}`,model_id:longModel,task:"text_to_motion",state,
  error_message:state === "FAILED" ? "The service could not finish generation. Check the connection and try again with the existing checkpoint." : null}));
const setup = {
  providers:{deepseek:{name:"DeepSeek",kind:"language",base_url:"https://api.deepseek.com",model:"deepseek-chat"}},
  active:{language:"local-language"},
  connections:[{id:longModel,provider:"deepseek",kind:"language",model:longModel,base_url:"http://127.0.0.1:8080/v1",has_key:false,
    verification:{generated:true,kind:"language",model:longModel,verified_at:"2026-10-12T00:00:00Z",result:{ready:true},elapsed_seconds:1}}],
  jobs:[{id:"local-deploy",status:"running",request:{recipe:"audio8"},percent:64,step:4,total_steps:6,stage_percent:70,
    message:"Verifying the existing checkpoint before starting the local service.",file:`models/${longModel}/checkpoint.safetensors`,downloaded_bytes:700,total_bytes:1000,
    logs:[{time:1,message:"Checking local model files"}]}],
  services:[],recipes:[{id:"audio8",name:"Audio8",storage_gib:4,license_url:"https://huggingface.co/audio8"}],
};

async function openPage(path) {
  const page = await browser.newPage({viewport:{width:1440,height:900},reducedMotion:"reduce"});
  page.setDefaultTimeout(15_000);
  await page.addInitScript(()=>{localStorage.setItem("virea.language.v1","en");localStorage.setItem("virea.theme.v1","dark");});
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let json;
    if (path === "/api/v1/models") json=models;
    else if (path === "/api/v1/jobs") json=jobs;
    else if (path === "/api/v1/health") json={status:"ready",control_plane_ready:true,version:"layout-test"};
    else if (path === "/api/v1/state") json={virea_home:"layout-fixture",events_url:"",revision:{jobs:"1",models:"1",results:"1",workers:"1",installations:"1"}};
    else if (path === "/api/v1/execution-domains") json={execution_domains:[],host_execution_domain:"windows-native"};
    else if (path === "/api/v1/onboarding") json=setup;
    else if (path.endsWith("/activity")) json={events:[],cursor:0,reset:false};
    else if (path.endsWith("/model-deployments")) json=[];
    else if (path.endsWith("/model-library")) json={models:[]};
    else if (path.endsWith("/resolve")) json={models:[{id:"deepseek-chat",name:"DeepSeek Chat"}],voices:[],model:"deepseek-chat",voice:"",tested:false};
    else if (path.endsWith("/environments")) json={virea_home:`D:/VIREA/${longModel}/.virea-runtime`,domains:[],conda:{environments:[]},runtimes:[]};
    else if (path.endsWith("/discover")) json={platform:"Windows",architecture:"AMD64",free_disk_gib:100,data_directory:"local/home",services:[],vrchat_supported:true};
    else if (path.endsWith("motion-backends")) json={default:"motioncraft",backends:[{id:"motioncraft",name:"MotionCraft",configured:true,ready:true}]};
    else if (path.endsWith("/voices")) json={voices:[]};
    else if (path.endsWith("/vrchat") || path.endsWith("/vrchat/connect")) json={connected:true,ready:false,session:{id:"layout-test"},config:{mode:"generated_vr",auto_bind:true,motion_backend:"motioncraft"},feedback:{values:{},query:{}},recent_performances:[]};
    else if (path.endsWith("/vrchat/clients")) json={configured:false,clients:{ai:{running:false,stage:"stopped"},observer:{running:false,stage:"stopped"}}};
    else return route.fulfill({status:404,json:{detail:"No runtime in isolated layout fixture"}});
    await route.fulfill({json});
  });
  await page.goto(server.resolvedUrls.local[0]+path);
  await page.locator(".mw-chrome").waitFor();
  return page;
}

async function preferences(page,language,theme="dark") {
  if (await page.locator("html").getAttribute("lang") !== language) {
    await page.getByRole("button",{name:/^(Switch to Chinese|切换为英语)$/}).click();
  }
  for(let i=0;i<3 && await page.locator("html").getAttribute("data-theme") !== theme;i++)
    await page.getByRole("button",{name:/^(Appearance:|外观：)/}).click();
  await page.waitForFunction(({language,theme})=>document.documentElement.lang===language&&document.documentElement.dataset.theme===theme,{language,theme});
}

async function screenshot(page,name) {
  if (!process.env.VIREA_LAYOUT_SCREENSHOTS) return;
  mkdirSync(process.env.VIREA_LAYOUT_SCREENSHOTS,{recursive:true});
  await page.screenshot({path:resolve(process.env.VIREA_LAYOUT_SCREENSHOTS,`${name}.png`),fullPage:true});
}

async function assertNoHorizontalOverflow(page,label) {
  const overflow = await page.evaluate(() => {
    const rows = [];
    if(document.documentElement.scrollWidth > innerWidth + 1) rows.push({element:"document",width:innerWidth,scrollWidth:document.documentElement.scrollWidth});
    for(const el of document.querySelectorAll("body *")) {
      if(el.clientWidth < 4 || !el.getClientRects().length) continue;
      const css=getComputedStyle(el);
      if(["auto","scroll"].includes(css.overflowX) && el.scrollWidth > el.clientWidth + 1)
        rows.push({element:`${el.tagName}#${el.id}.${String(el.className)}`,width:el.clientWidth,scrollWidth:el.scrollWidth});
    }
    return rows;
  });
  assert.deepEqual(overflow,[],label);
}

async function assertSettingsFit(page,label) {
  await assertNoHorizontalOverflow(page,label);
  const boxes=await page.locator('#settings-dialog').evaluate(dialog=>{
    const rect=dialog.getBoundingClientRect(),body=dialog.querySelector('.settings-scroll,.dialog-body').getBoundingClientRect();
    return {inside:rect.top>=0&&rect.bottom<=innerHeight&&body.bottom<=rect.bottom,dialogHeight:rect.height,bodyHeight:body.height};
  });
  assert.ok(boxes.inside && boxes.bodyHeight>0,`${label}: ${JSON.stringify(boxes)}`);
}

const sizes = [{width:1920,height:540},{width:1440,height:900},{width:1280,height:720},{width:1112,height:517},{width:1024,height:420},{width:768,height:500},{width:568,height:320},{width:390,height:844},{width:320,height:568}];

test("Motion Lab activity rows contain status text, including wrapped errors and enlarged type",{skip:!executablePath,timeout:90_000},async()=>{
  const page=await openPage("");
  try {
    await page.locator(".activity-row").first().waitFor();
    await page.locator("#prompt").waitFor();
    assert.ok(await page.locator(".activity-card").evaluate(el=>parseFloat(getComputedStyle(el).paddingTop))>=18,"Page spacing must survive HeroUI/Tailwind cascade resets");
    for(const language of ["en","zh-CN"]) {
      await preferences(page,language);
      for(const size of sizes) {
        await page.setViewportSize(size);
        await page.locator(".activity-card").scrollIntoViewIfNeeded();
        await screenshot(page,`motion-${language}-${size.width}`);
        await assertNoHorizontalOverflow(page,`Motion Lab ${language} ${size.width}`);
        const panelHeights=await page.locator(".comparison-panel").evaluateAll(panels=>panels.map(panel=>panel.getBoundingClientRect().height));
        assert.ok(Math.abs(panelHeights[0]-panelHeights[1])<=1,`Comparison panels share height at ${size.width}: ${panelHeights}`);
        const clipped=await page.locator(".activity-row").evaluateAll(rows=>rows.flatMap(row=>{
          const r=row.getBoundingClientRect();
          return [...row.querySelectorAll(".activity-copy,code")].filter(child=>child.getBoundingClientRect().bottom > r.bottom-3 || child.getBoundingClientRect().top < r.top+3).map(el=>el.textContent);
        }));
        assert.deepEqual(clipped,[],`Activity content inside highlight at ${size.width}`);
      }
    }
    await page.addStyleTag({content:'.activity-copy :is(strong,small){font-size:20px!important}'});
    const row=page.locator(".activity-row.failed");
    assert.equal(await row.evaluate(el=>el.scrollHeight<=el.clientHeight),true,"Larger text must grow the activity row");
    assert.equal(await row.evaluate(el=>getComputedStyle(el).opacity),"1","Non-actionable status rows remain readable");
  } finally {await page.close();}
});

test("VRChat reflows the central pane, clients, composer and live views at each available width",{skip:!executablePath,timeout:90_000},async()=>{
  const page=await openPage("vrchat.html");
  try {
    await page.locator(".client-launch-card").first().waitFor();
    for(const language of ["en","zh-CN"]) {
      await preferences(page,language,language === "en" ? "dark" : "light");
      for(const size of sizes) {
        await page.setViewportSize(size);
        await screenshot(page,`vrchat-${language}-${size.width}`);
        await assertNoHorizontalOverflow(page,`VRChat ${language} ${size.width}`);
        await page.locator("#toggle-views").click();
        await page.locator(".manual-help-toggle").click();
        if(size.width===1112) await screenshot(page,`vrchat-views-${language}`);
        await assertNoHorizontalOverflow(page,`VRChat with live views ${language} ${size.width}`);
        await page.locator(".views-heading button").click();
        await page.locator("#connection-settings").click();
        if(size.width===390) await screenshot(page,`vrchat-settings-${language}`);
        await assertSettingsFit(page,`VRChat settings ${language} ${size.width}`);
        await page.locator("#close-settings").click();
        const composer=await page.locator(".composer-wrap").boundingBox();
        assert.ok(composer.y>=0 && composer.y+composer.height<=size.height+1,`Composer stays in ${size.width}x${size.height}: ${JSON.stringify(composer)}`);
      }
    }
    assert.equal(await page.locator("#chat-scroll").evaluate(el=>getComputedStyle(el).scrollbarWidth),"thin");
  } finally {await page.close();}
});

test("Set Up cards, verification, progress, forms and menus fit narrow and short windows",{skip:!executablePath,timeout:90_000},async()=>{
  const page=await openPage("setup.html");
  try {
    await page.locator(".mw-job").waitFor();
    for(const language of ["en","zh-CN"]) {
      await preferences(page,language);
      for(const size of sizes) {
        await page.setViewportSize(size);
        await page.locator(".mw-job").scrollIntoViewIfNeeded();
        await screenshot(page,`setup-${language}-${size.width}`);
        await assertNoHorizontalOverflow(page,`Set Up ${language} ${size.width}`);
      }
    }
    await page.locator('[data-native-select="provider"]').click();
    await assertNoHorizontalOverflow(page,"Provider popover");
    await page.keyboard.press("Escape");
    await page.locator("#saved-connections .verification summary").click();
    await assertNoHorizontalOverflow(page,"Expanded verification");
  } finally {await page.close();}
});

test("Character Studio settings and drawers stay within narrow and short viewports",{skip:!executablePath,timeout:90_000},async()=>{
  const page=await openPage("character.html");
  try {
    for(const language of ["en","zh-CN"]) {
      await preferences(page,language);
      for(const size of sizes) {
        await page.setViewportSize(size);
        await screenshot(page,`character-${language}-${size.width}`);
        await assertNoHorizontalOverflow(page,`Character Studio ${language} ${size.width}`);
        await page.getByRole("button",{name:language === "en" ? "Character settings" : "角色与设置",exact:true}).click();
        if(size.width===390) await screenshot(page,`character-settings-${language}`);
        await assertSettingsFit(page,`Character settings ${language} ${size.width}`);
        await page.locator("#settings-close").click();
        const composerFits=await page.locator("#composer").evaluate(el=>{
          const rect=el.getBoundingClientRect(),panel=el.closest('.chat-dock').getBoundingClientRect();
          return rect.top>=panel.top&&rect.bottom<=panel.bottom&&rect.bottom<=innerHeight;
        });
        assert.ok(composerFits,`Character composer visible at ${size.width}x${size.height}`);
        await page.locator("#trace-toggle").click();
        const panel=await page.locator(".trace-drawer").boundingBox();
        assert.ok(panel.x>=0 && panel.x+panel.width<=size.width+1,`Diagnostics fit at ${size.width}`);
        await assertNoHorizontalOverflow(page,`Character diagnostics ${language} ${size.width}`);
        await page.locator("#trace-toggle").click();
      }
    }
  } finally {await page.close();}
});
