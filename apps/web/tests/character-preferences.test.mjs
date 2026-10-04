import test from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { createServer } from "vite";

test("settings imports, previews, restores and deletes a reference voice", { timeout: 30000 }, async t => {
  const executablePath = [process.env.VIREA_E2E_BROWSER_PATH,
    "C:/Program Files/Google/Chrome/Application/chrome.exe", chromium.executablePath()].find(path => path && existsSync(path));
  if (!executablePath) { t.skip("Chromium is not installed"); return; }
  const server = await createServer({ root: resolve(import.meta.dirname, ".."), base: "/", server: { port: 0 } });
  await server.listen();
  t.after(() => server.close());
  const browser = await chromium.launch({ executablePath, headless: true, args: ["--autoplay-policy=no-user-gesture-required"] });
  t.after(() => browser.close());
  const page = await browser.newPage();
  const origin = server.resolvedUrls.local[0];
  let voices = [], imported, previewed, offline = false;
  const pcm = Buffer.alloc(44 + 24000 * 2);
  pcm.write("RIFF"); pcm.writeUInt32LE(pcm.length - 8, 4); pcm.write("WAVEfmt ", 8);
  pcm.writeUInt32LE(16, 16); pcm.writeUInt16LE(1, 20); pcm.writeUInt16LE(1, 22);
  pcm.writeUInt32LE(24000, 24); pcm.writeUInt32LE(48000, 28); pcm.writeUInt16LE(2, 32);
  pcm.writeUInt16LE(16, 34); pcm.write("data", 36); pcm.writeUInt32LE(pcm.length - 44, 40);
  await page.route("**/voice-settings-test", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.route("**/api/v1/characters/**", async route => {
    const request = route.request();
    if (request.url().endsWith("/preferences")) return route.fulfill({ json: { voice: "zf_001", persona: "默认设定", voices: offline ? [] : voices, speech_error: offline ? "dots.tts 服务不可用" : null } });
    if (request.url().endsWith("/voice-preview")) {
      previewed = request.postDataJSON();
      return route.fulfill({ contentType: "audio/wav", body: pcm });
    }
    if (request.method() === "POST") {
      imported = request.postDataJSON();
      const voice = { id: "ref_123", name: imported.name, transcript: imported.transcript, seconds: 10, language: "auto" };
      voices.push(voice); return route.fulfill({ status: 201, json: voice });
    }
    if (request.method() === "DELETE") { voices = []; return route.fulfill({ status: 204 }); }
    return route.abort();
  });
  const mount = async () => {
    await page.goto(`${origin}voice-settings-test`);
    await page.evaluate(async () => {
      const { studioShell } = await import("/src/character/ui/shell.ts");
      const { StudioPreferences } = await import("/src/character/ui/preferences.ts");
      document.querySelector("#root").innerHTML = studioShell;
      document.querySelector("#settings-dialog").showModal();
      window.preferences = new StudioPreferences(document.querySelector("#root"), error => {
        document.querySelector("#settings-error").textContent = error.message;
      });
      await window.preferences.ready;
    });
  };
  await mount();
  assert.equal(await page.locator("#voice-preview").isDisabled(), true);
  await page.locator("#voice-import").click();
  await page.waitForFunction(() => document.querySelector("#voice-import-status").textContent.includes("逐字文本"));
  await page.locator("#voice-reference").setInputFiles({ name: "reference.wav", mimeType: "audio/wav", buffer: pcm });
  await page.locator("#voice-name").fill("我的克隆声音");
  await page.locator("#voice-transcript").fill("这是录音的准确文本。");
  await page.locator("#voice-import").click();
  await page.waitForFunction(() => document.querySelector("#voice").value === "ref_123");
  assert.equal(imported.transcript, "这是录音的准确文本。");
  assert.equal(Buffer.from(imported.audio, "base64").compare(pcm), 0);
  assert.equal(await page.locator("#voice-preview").isEnabled(), true);
  await page.locator("#voice-preview").click();
  await page.waitForFunction(() => !document.querySelector("#voice-player").hidden);
  assert.equal(previewed.voice, "ref_123");
  await page.locator("#persona").fill("保留角色设定");
  await page.locator("#persona").dispatchEvent("change");
  await mount();
  assert.equal(await page.locator("#voice").inputValue(), "ref_123");
  assert.equal(await page.locator("#persona").inputValue(), "保留角色设定");
  offline = true;
  await mount();
  assert.match(await page.locator("#voice-status").textContent(), /不可用/);
  assert.equal(await page.locator("#persona").inputValue(), "保留角色设定");
  await page.locator("#voice-refresh").click();
  await page.waitForFunction(() => !document.querySelector("#voice-refresh").disabled);
  assert.match(await page.locator("#voice-status").textContent(), /不可用/);
  await page.locator("#persona").dispatchEvent("change");
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem("virea.preferences")).voice), "ref_123");
  offline = false;
  await page.locator("#voice-refresh").click();
  await page.waitForFunction(() => document.querySelector("#voice").value === "ref_123");
  await page.locator("#voice-delete").click();
  await page.waitForFunction(() => document.querySelector("#voice").options.length === 0);
  assert.equal(await page.locator("#voice-preview").isDisabled(), true);
  assert.deepEqual(await page.evaluate(() => window.preferences.values()), { persona: "保留角色设定" });
});
