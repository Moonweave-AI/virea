import test from "node:test";
import assert from "node:assert/strict";
import {existsSync} from "node:fs";
import {resolve} from "node:path";
import {chromium} from "playwright";
import {createServer} from "vite";
import tailwindcss from "@tailwindcss/vite";

const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,"C:/Program Files/Google/Chrome/Application/chrome.exe","C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe","/usr/bin/chromium",chromium.executablePath()].find(p=>p&&existsSync(p));

test("HeroUI selects follow native value hydration, selection indices and form resets",{skip:!executablePath,timeout:30_000},async()=>{
  const server=await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
  await server.listen();
  const browser=await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
  try {
    const page=await browser.newPage();
    await page.route("**/select-fixture",route=>route.fulfill({contentType:"text/html",body:'<form><label>Motion backend<select id="backend"><option value="motioncraft">MotionCraft</option><option value="syntalker">SynTalker</option></select></label></form><p id="changes">0</p>'}));
    await page.goto(server.resolvedUrls.local[0]+"select-fixture");
    await page.evaluate(async()=>{
      const {enhanceSelects}=await import('/src/studio/selects.tsx');
      const native=document.querySelector('#backend');
      native.addEventListener('change',()=>{document.querySelector('#changes').textContent=String(Number(document.querySelector('#changes').textContent)+1);});
      enhanceSelects(document.body);
    });
    const trigger=page.locator('[data-native-select="backend"]');
    await trigger.getByText('MotionCraft',{exact:true}).waitFor();
    await page.evaluate(()=>{document.querySelector('#backend').value='syntalker';});
    await trigger.getByText('SynTalker',{exact:true}).waitFor();
    assert.equal(await page.locator('#changes').textContent(),'0','Server hydration must not submit a settings change');
    await page.evaluate(()=>{document.querySelector('#backend').selectedIndex=0;});
    await trigger.getByText('MotionCraft',{exact:true}).waitFor();
    await page.evaluate(()=>{document.querySelector('#backend').value='syntalker';});
    await trigger.getByText('SynTalker',{exact:true}).waitFor();
    await page.evaluate(()=>document.querySelector('form').reset());
    await trigger.getByText('MotionCraft',{exact:true}).waitFor();
    assert.equal(await page.locator('#changes').textContent(),'0');
    await trigger.click();
    await page.getByRole('option',{name:'SynTalker',exact:true}).click();
    assert.equal(await page.locator('#backend').inputValue(),'syntalker');
    assert.equal(await page.locator('#changes').textContent(),'1');
  } finally {await browser.close();await server.close();}
});

test("studios keep one navigation, translate controls, preserve content and open settings on demand",{skip:!executablePath,timeout:60_000},async()=>{
  const server=await createServer({configFile:false,plugins:[tailwindcss()],root:resolve(import.meta.dirname,".."),server:{host:"127.0.0.1",port:0}});
  await server.listen();
  const browser=await chromium.launch({executablePath,headless:true,args:["--mute-audio"]});
  try {
    const page=await browser.newPage({viewport:{width:1400,height:1000}});
    const errors=[];page.on("pageerror",e=>errors.push(e.message));
    await page.addInitScript(()=>localStorage.setItem("virea.language.v1","en"));
    await page.route("**/api/v1/**",async route=>{
      const path=new URL(route.request().url()).pathname;
      if(path.endsWith("motion-backends"))return route.fulfill({json:{default:"motioncraft",backends:[{id:"motioncraft",name:"MotionCraft",configured:true,ready:true},{id:"syntalker",name:"SynTalker",configured:true,ready:true}]}});
      if(path.endsWith("/voices"))return route.fulfill({json:{voices:[]}});
      if(path.endsWith("/vrchat")||path.endsWith("/vrchat/connect"))return route.fulfill({json:{connected:true,ready:false,session:{id:"ui-test"},config:{mode:"generated_vr",auto_bind:true,motion_backend:"motioncraft"},feedback:{values:{},query:{}},recent_performances:[]}});
      if(path.endsWith("/vrchat/clients"))return route.fulfill({json:{configured:true,clients:{ai:{running:false,stage:"stopped",detail:"尚未启动"},observer:{running:false,stage:"stopped",detail:"尚未启动"}}}});
      if(path.includes("/views/"))return route.fulfill({status:404,json:{detail:"window_not_found"}});
      return route.fulfill({status:503,json:{detail:"Service offline in isolated UI test"}});
    });
    await page.goto(server.resolvedUrls.local[0]+"character.html");
    const constraints=await page.evaluate(async()=>{
      const {translateLabel}=await import('/src/studio/legacy.ts');
      const {setLanguage}=await import('/src/studio/preferences.ts');
      const en=translateLabel('最小值 2 · 最大值 9.8 · 步长 0.2');
      setLanguage('zh-CN');
      const zh=translateLabel(en);
      setLanguage('en');
      return {en,zh};
    });
    assert.deepEqual(constraints,{en:'Min 2 · Max 9.8 · Step 0.2',zh:'最小值 2 · 最大值 9.8 · 步长 0.2'});
    assert.equal(await page.locator("#settings-dialog").isVisible(),false);
    assert.equal(await page.locator("#new-session").count(),0);
    assert.equal(await page.locator(".mw-chrome").count(),1);
    await page.getByRole("button",{name:"Character settings",exact:true}).click();
    await page.getByText("Choose a VRM character",{exact:true}).waitFor();
    await page.locator('[data-native-select="motion-backend"]').click();
    await page.getByRole("option",{name:"SynTalker",exact:true}).click();
    assert.equal(await page.locator("#motion-backend").inputValue(),"syntalker");
    await page.getByRole("button",{name:"Close settings",exact:true}).click();
    await page.getByRole("button",{name:"Switch to Chinese",exact:true}).click();
    await page.getByRole("button",{name:"角色与设置",exact:true}).click();
    await page.getByText("选择 VRM 角色",{exact:true}).waitFor();
    await page.getByRole("button",{name:"关闭设置",exact:true}).click();
    await page.getByRole("button",{name:"切换为英语",exact:true}).click();
    await page.getByRole("button",{name:"Character settings",exact:true}).click();
    await page.getByText("Choose a VRM character",{exact:true}).waitFor();
    await page.getByRole("button",{name:"Close settings",exact:true}).click();
    // Translation touches authored controls, never actual user/model content.
    await page.evaluate(()=>{
      const article=document.createElement("div");article.className="message-content";article.textContent="等待生成";document.querySelector("#character").append(article);
    });
    assert.equal(await page.locator(".message-content").textContent(),"等待生成");
    await page.locator('#trace-toggle').click();
    await page.evaluate(async()=>{
      const {StudioDiagnostics}=await import('/src/character/ui/diagnostics.ts');
      const diagnostics=new StudioDiagnostics(document.querySelector('#character'));
      diagnostics.update({id:'diagnostic-copy-test',epoch:1,motion_backend:'motioncraft',events:[{kind:'user_message',epoch:1,sequence:1,at_seconds:0}],metrics:{}}, {
        recording:{duration_seconds:0,speech:[],drivers:[]},speech:{active:false,remaining_seconds:0},
        retracting:false,body_owner:'hold',body_active:false,body_duration:0,body_elapsed:0,body_status:'idle',
        phase:'',preview:false,reason:'',synchronization:{marks:{}},
        head_speed_deg_s:0,peak_head_speed_deg_s:0,peak_head_delta_deg:0,peak_head_frame_seconds:0,
        peak_head_at_seconds:0,peak_head_owner:'hold',peak_head_joint:'head',max_joint_speed_deg_s:0,worst_joint:'head',
        ground_clearance:0,retarget_max_angle:0,
      });
    });
    assert.equal(/[\u4e00-\u9fff]/.test(await page.locator('#trace-live').innerText()),false,'Live execution metrics are translated');
    assert.match(await page.locator('#trace-events summary').innerText(),/User input/);
    await page.getByRole('button',{name:'Switch to Chinese',exact:true}).click();
    assert.match(await page.locator('#trace-live').innerText(),/头部角速度/);
    await page.getByRole('button',{name:'切换为英语',exact:true}).click();
    assert.match(await page.locator('#trace-live').innerText(),/Head angular speed/);
    await page.locator('#trace-toggle').click();
    await page.setViewportSize({width:390,height:844});
    await page.getByRole("button",{name:"Open navigation",exact:true}).click();
    assert.equal(await page.getByRole("dialog",{name:"VIREA",exact:true}).isVisible(),true);
    await page.keyboard.press("Escape");
    await page.getByRole("button",{name:"Character settings",exact:true}).click();
    await page.getByRole("button",{name:"Close settings",exact:true}).click();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.setViewportSize({width:1400,height:1000});
    await page.goto(server.resolvedUrls.local[0]+"vrchat.html");
    await page.getByText("Looking for the AI client",{exact:true}).first().waitFor();
    await page.getByRole("button",{name:"Open live views",exact:true}).click();
    await page.getByRole("button",{name:"Controls ?",exact:true}).click();
    const untranslated=()=>page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getClientRects().length&&!e.closest('script,style,pre,textarea,option,.message-content,#conversations')).flatMap(e=>[...e.childNodes].filter(n=>n.nodeType===3&&/[\u4e00-\u9fff]/.test(n.textContent||'')).map(n=>n.textContent.trim())));
    await page.waitForTimeout(100);
    assert.deepEqual(await untranslated(),[],"English live views and controls contain no untranslated interface copy");
    await page.getByRole("button",{name:"Switch to Chinese",exact:true}).click();
    await page.getByText("正在寻找 AI 客户端",{exact:true}).first().waitFor();
    await page.getByRole("button",{name:"键位 ?",exact:true}).waitFor();
    await page.getByRole("button",{name:"切换为英语",exact:true}).click();
    await page.getByRole("button",{name:"Character & output settings ↗",exact:true}).click();
    assert.deepEqual(await untranslated(),[],"English settings remain translated after switching twice");
    await page.getByRole("button",{name:"Diagnostics",exact:true}).click();
    assert.deepEqual(await untranslated(),[],"English diagnostics labels are translated");
    assert.deepEqual(errors,[]);
  } finally {await browser.close();await server.close();}
});
